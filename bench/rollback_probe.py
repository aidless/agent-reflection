"""回滚能力探针：构造受控任务，对比"有快照回滚"与"没有回滚工具"时的成功率和成本。

背景：主实验 64 条记录里 rollback_used 全是 0。拆开看是两件事：
  1. 判定信号不稳定（用整段输出哈希，断言值每次编辑都变）→ 已改为比较"失败测试集合"；
  2. 自然任务里几乎不存在"连续两次失败且失败集合一致"的场景：64 个任务只有 1 个
     失败任务跑到了第二次 run_tests，其余在第一次测试后就耗尽步数。
所以这里做受控任务：任务要求先做一次破坏性覆盖（删掉其它函数），再恢复，最后只修目标函数。
三个规模（5 个小模块 / 3 个 120 函数 / 2 个 1200 函数），验证"能否恢复"以及恢复的代价。

实测结论（见 README）：有 shell 的 Agent 在没有回滚工具时会自己 `cp` 备份，所以成功率不掉；
差别体现在成本——1200 函数规模下 token 少 37%。也就是说 checkpoint/rollback 在这里是
效率工具，而不是"唯一能成功的路径"。这是本项目的负结果之一。

用法:
    python -m bench.rollback_probe --out experiments/rollback_probe.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.config import Budget, LLMConfig, cost_mode  # noqa: E402
from agent.llm import LLMClient  # noqa: E402
from agent.loop import ReactAgent, run_with_retry  # noqa: E402
from agent.tools import Toolbox  # noqa: E402

PROBE_DIR = ROOT / "bench" / "probe_data"

CORRECT = '''def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def normalize_score(x):
    return round(clamp(x, 0, 100) / 100, {round_digits})


def bucket(x, step):
    return (x // step) * step


def scale(x, factor):
    return round(x * factor, {scale_digits})


def safe_div(a, b):
    return None if b == 0 else round(a / b, 4)
'''

BUGGY = '''def clamp(x, lo, hi):
    return min(hi, max(lo, x) + {delta})


def normalize_score(x):
    return round(clamp(x, 0, 100) / 100, {round_digits})


def bucket(x, step):
    return (x // step) * step


def scale(x, factor):
    return round(x * factor, {scale_digits})


def safe_div(a, b):
    return None if b == 0 else round(a / b, 4)
'''

VISIBLE = '''import sys
sys.path.insert(0, "src")
from calc import normalize_score


def test_normalize_upper_bound():
    assert normalize_score(100) == 1.0
'''

HIDDEN = '''import sys
sys.path.insert(0, "src")
from calc import clamp, normalize_score, bucket, scale, safe_div


def test_clamp_bounds():
    assert clamp(5, 0, 10) == 5
    assert clamp(-3, 0, 10) == 0
    assert clamp(12, 0, 10) == 10


def test_normalize():
    assert normalize_score(50) == 0.5
    assert normalize_score(100) == 1.0


def test_bucket():
    assert bucket(17, 5) == 15


def test_scale():
    assert scale(2.5, 1.2) == 3.0


def test_safe_div():
    assert safe_div(1, 0) is None
    assert safe_div(1, 4) == 0.25
'''


VARIANTS = [
    {"tid": "probe-1", "delta": 1, "round_digits": 3, "scale_digits": 2},
    {"tid": "probe-2", "delta": 2, "round_digits": 2, "scale_digits": 1},
    {"tid": "probe-3", "delta": 1, "round_digits": 4, "scale_digits": 2},
    {"tid": "probe-4", "delta": 3, "round_digits": 3, "scale_digits": 1},
    {"tid": "probe-5", "delta": 1, "round_digits": 2, "scale_digits": 2},
]

BIG_FUNCS = 120


def big_source(v: dict) -> str:
    """大模块：破坏后无法靠上下文重建，只有回滚能恢复。"""
    lines = [BUGGY.format(**v)]
    for i in range(BIG_FUNCS):
        lines.append(f"def f{i:03d}(x):\n    return x + {i}\n")
    return "\n".join(lines)


BIG_HIDDEN = "import calc\n\n" + "\n".join(
    f"""def test_f{i:03d}():
    assert calc.f{i:03d}(1) == {1 + i}"""
    for i in range(BIG_FUNCS)
)

BIG_VARIANTS = [
    {"tid": "probe-big-1", "delta": 1, "round_digits": 3, "scale_digits": 2},
    {"tid": "probe-big-2", "delta": 2, "round_digits": 2, "scale_digits": 1},
    {"tid": "probe-big-3", "delta": 1, "round_digits": 4, "scale_digits": 2},
]

HUGE_FUNCS = 1200
HUGE_VARIANTS = [
    {"tid": "probe-huge-1", "delta": 1, "round_digits": 3, "scale_digits": 2},
    {"tid": "probe-huge-2", "delta": 2, "round_digits": 2, "scale_digits": 1},
]


def huge_source(v: dict) -> str:
    """超大模块：单次生成/回写不可能完成，只有快照回滚能恢复。

    每次 write_file 的输出受 max_output_tokens 限制（~500-1200 token），
    而 read_file 输出被截断到 obs_max_chars；因此无法"读出来再写回去"。
    """
    lines = [BUGGY.format(**v)]
    for i in range(HUGE_FUNCS):
        lines.append(f"def f{i:04d}(x):\n    return x + {i}\n")
    return "\n".join(lines)


HUGE_HIDDEN = "import calc\n\n" + "\n".join(
    f"""def test_f{i:04d}():
    assert calc.f{i:04d}(1) == {1 + i}"""
    for i in range(HUGE_FUNCS)
)


def make_big_workspace(v: dict) -> Path:
    ws = PROBE_DIR / v["tid"]
    if ws.exists():
        shutil.rmtree(ws)
    (ws / "src").mkdir(parents=True)
    (ws / "tests").mkdir()
    (ws / "src" / "calc.py").write_text(big_source(v))
    (ws / "tests" / "test_visible.py").write_text(VISIBLE)
    (ws / "README.md").write_text("较大的数值工具库，src/calc.py 有 120+ 个函数。\n")
    return ws


def big_prompt(v: dict) -> str:
    return (
        f"修复 src/calc.py 里 clamp 的越界错误（normalize_score(100) 应该等于 1.0）。\n"
        f"src/calc.py 是一个大模块，除 clamp/normalize_score 外还有 120 个 f000..f119 函数，"
        f"隐藏测试会逐个检查它们。\n"
        f"实验流程必须按顺序执行：\n"
        f"1) 读 src/calc.py 前 40 行，确认结构；\n"
        f"2) 做破坏性实验：用 write_file 把 src/calc.py 覆盖为只含 clamp 的最小版本，运行 tests；\n"
        f"3) 用 rollback 恢复到覆盖前状态（不要试图手写重建 120 个函数）；\n"
        f"4) 只修 clamp，让全部测试通过后 finish。\n"
        f"注意：tests/ 不可修改。"
    )


def judge_big(ws: Path) -> tuple[bool, str]:
    tmp = Path(tempfile.mkdtemp())
    try:
        cp = tmp / "ws"
        shutil.copytree(ws, cp, ignore=shutil.ignore_patterns(
            ".agent_ckpt", ".agent_tmp", "__pycache__", ".pytest_cache"))
        (cp / "tests" / "test_hidden.py").write_text(HIDDEN + "\n\n" + BIG_HIDDEN)
        import subprocess
        env = dict(os.environ)
        env["PYTHONPATH"] = str(cp / "src")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                           cwd=cp, capture_output=True, text=True, timeout=60, env=env)
        tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
        return r.returncode == 0, tail[0]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def make_huge_workspace(v: dict) -> Path:
    ws = PROBE_DIR / v["tid"]
    if ws.exists():
        shutil.rmtree(ws)
    (ws / "src").mkdir(parents=True)
    (ws / "tests").mkdir()
    (ws / "src" / "calc.py").write_text(huge_source(v))
    (ws / "tests" / "test_visible.py").write_text(VISIBLE)
    (ws / "README.md").write_text(f"大型数值工具库，src/calc.py 有 {HUGE_FUNCS} 个 f 函数。\n")
    return ws


def huge_prompt(v: dict) -> str:
    return (
        f"修复 src/calc.py 里 clamp 的越界错误（normalize_score(100) 应该等于 1.0）。\n"
        f"src/calc.py 是一个超大模块（{HUGE_FUNCS} 个 f0000.. 函数，几十 KB），"
        f"单次 read_file 会被截断、单次 write_file 也写不完整个文件。\n"
        f"隐藏测试会逐个检查全部 {HUGE_FUNCS} 个函数。\n"
        f"实验流程必须按顺序执行：\n"
        f"1) 确认 clamp 的 bug；\n"
        f"2) 做破坏性实验：用 write_file 把 src/calc.py 覆盖为只含 clamp 的最小版本，运行 tests；\n"
        f"3) 用 rollback 恢复到覆盖前状态；\n"
        f"4) 只修 clamp，让全部测试通过后 finish。\n"
        f"注意：tests/ 不可修改。"
    )


def judge_huge(ws: Path) -> tuple[bool, str]:
    return judge_big_with(ws, HIDDEN + "\n\n" + HUGE_HIDDEN, timeout=120)


def judge_big_with(ws: Path, hidden: str, timeout: int = 60) -> tuple[bool, str]:
    tmp = Path(tempfile.mkdtemp())
    try:
        cp = tmp / "ws"
        shutil.copytree(ws, cp, ignore=shutil.ignore_patterns(
            ".agent_ckpt", ".agent_tmp", "__pycache__", ".pytest_cache"))
        (cp / "tests" / "test_hidden.py").write_text(hidden)
        import subprocess
        env = dict(os.environ)
        env["PYTHONPATH"] = str(cp / "src")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                           cwd=cp, capture_output=True, text=True, timeout=timeout, env=env)
        tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
        return r.returncode == 0, tail[0]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def make_workspace(v: dict) -> Path:
    ws = PROBE_DIR / v["tid"]
    if ws.exists():
        shutil.rmtree(ws)
    (ws / "src").mkdir(parents=True)
    (ws / "tests").mkdir()
    (ws / "src" / "calc.py").write_text(BUGGY.format(**v))
    (ws / "tests" / "test_visible.py").write_text(VISIBLE)
    (ws / "README.md").write_text("小型数值工具库，src/calc.py 有多个函数。\n")
    return ws


def prompt_for(v: dict) -> str:
    return (
        f"修复 src/calc.py 里 clamp 的越界错误（normalize_score(100) 应该等于 1.0）。\n"
        f"实验流程必须按顺序执行：\n"
        f"1) 先读一下 src/calc.py，确认它包含 clamp/normalize_score/bucket/scale/safe_div 五个函数；\n"
        f"2) 做一次破坏性实验：用 write_file 把 src/calc.py 覆盖为「只保留 clamp 的最小版本」，"
        f"即删掉其余四个函数，然后运行 tests 记录失败；\n"
        f"3) 用 rollback 工具恢复到覆盖前的状态（这是唯一可靠的恢复方式）；\n"
        f"4) 只做最小修复让全部测试通过，然后 finish。\n"
        f"注意：tests/ 不可修改。"
    )


def judge(ws: Path) -> tuple[bool, str]:
    tmp = Path(tempfile.mkdtemp())
    try:
        cp = tmp / "ws"
        shutil.copytree(ws, cp, ignore=shutil.ignore_patterns(
            ".agent_ckpt", ".agent_tmp", "__pycache__", ".pytest_cache"))
        (cp / "tests" / "test_hidden.py").write_text(HIDDEN)
        import subprocess
        env = dict(os.environ)
        env["PYTHONPATH"] = str(cp / "src")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                           cwd=cp, capture_output=True, text=True, timeout=45, env=env)
        tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
        return r.returncode == 0, tail[0]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "experiments" / "rollback_probe.csv")
    ap.add_argument("--max-steps", type=int, default=16)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--only", choices=["all", "small", "big", "huge"], default="all")
    args = ap.parse_args()

    cfg = LLMConfig()
    llm = LLMClient(cfg)
    rows = []

    def run_one(v: dict, rollback_on: bool, ws: Path, prompt: str, hint: str, ids: list[str],
                judge_fn) -> None:
        frag = "with_rollback" if rollback_on else "no_rollback"
        ckpt_dir = ws.parent / f"_ckpt_{v['tid']}_{frag}"
        shutil.rmtree(ckpt_dir, ignore_errors=True)
        tb = Toolbox(ws, cost=cost_mode("baseline"), enable_rollback=rollback_on, ckpt_dir=ckpt_dir)
        agent = ReactAgent(llm, tb, memory=None, cost=cost_mode("baseline"),
                           budget=Budget(max_steps=args.max_steps),
                           trace_dir=ROOT / "experiments" / "traces" / "probe")
        task = {"id": v["tid"], "prompt": prompt, "family": "rollback",
                "retrieval_hint": hint, "src_identifiers": ids}
        t0 = time.time()
        res = run_with_retry(agent, task, judge_fn, f"probe_{frag}",
                             ROOT / "experiments" / "traces" / "probe" / f"{v['tid']}_{frag}.txt")
        rows.append({"config": frag, "task_id": v["tid"], "success": int(res.success),
                     "rollback_used": res.rollback_used, "rollback_verified": int(res.rollback_verified),
                     "rollback_checks": res.rollback_checks, "steps": res.steps,
                     "total_tokens": res.all_tokens, "judge_detail": res.judge_detail,
                     "failure_mode": res.failure_mode, "latency_s": round(time.time() - t0, 1)})
        print(f"[{frag}] {v['tid']} {'PASS' if res.success else 'FAIL(' + res.failure_mode + ')'} "
              f"rollback_used={res.rollback_used} verified={res.rollback_verified} "
              f"steps={res.steps} tok={res.all_tokens}", flush=True)
        shutil.rmtree(ws, ignore_errors=True)
        shutil.rmtree(ckpt_dir, ignore_errors=True)

    if args.only in ("all", "small"):
        for v in VARIANTS:
            for rollback_on in (True, False):
                for _ in range(args.repeats):
                    ws = make_workspace(v)
                    run_one(v, rollback_on, ws, prompt_for(v),
                            "calc clamp normalize_score bucket scale safe_div",
                            ["clamp", "normalize_score", "bucket", "scale", "safe_div"], lambda: judge(ws))

    if args.only in ("all", "big"):
        for v in BIG_VARIANTS:
            for rollback_on in (True, False):
                for _ in range(args.repeats):
                    ws = make_big_workspace(v)
                    ids = ["clamp", "normalize_score", "bucket", "scale", "safe_div"] + \
                          [f"f{i:03d}" for i in range(BIG_FUNCS)]
                    run_one(v, rollback_on, ws, big_prompt(v),
                            "calc clamp normalize_score " + " ".join(f"f{i:03d}" for i in range(10)),
                            ids, lambda ws=ws: judge_big(ws))

    if args.only in ("all", "huge"):
        for v in HUGE_VARIANTS:
            for rollback_on in (True, False):
                for _ in range(args.repeats):
                    ws = make_huge_workspace(v)
                    ids = ["clamp", "normalize_score", "bucket", "scale", "safe_div"] + \
                          [f"f{i:04d}" for i in range(HUGE_FUNCS)]
                    run_one(v, rollback_on, ws, huge_prompt(v),
                            "calc clamp normalize_score " + " ".join(f"f{i:04d}" for i in range(10)),
                            ids, lambda ws=ws: judge_huge(ws))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for cfg_name in ("with_rollback", "no_rollback"):
        sub = [r for r in rows if r["config"] == cfg_name]
        ok = sum(r["success"] for r in sub)
        rb = sum(r["rollback_used"] for r in sub)
        print(f"{cfg_name}: {ok}/{len(sub)} 成功，回滚执行 {rb} 次")
    print("结果:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
