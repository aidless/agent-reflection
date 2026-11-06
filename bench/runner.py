"""A/B 实验执行器：同一批任务、同一模型、同一预算，跑多组 arm。"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from pathlib import Path

from agent.config import Budget, LLMConfig, cost_mode
from agent.llm import LLMClient
from agent.loop import ReactAgent, run_with_retry
from agent.memory import ReflectionMemory, infer_categories
from agent.tools import Toolbox

from .judge import judge
from .tasks import DATA_DIR, load_tasks, select_main, workspace_of

ROOT = Path(__file__).resolve().parent.parent
FIELDS = [
    "arm", "task_id", "family", "success", "judge_detail", "failure_mode", "steps", "calls",
    "tool_calls", "plan_calls", "reflect_calls", "prompt_tokens", "completion_tokens",
    "reflect_tokens", "total_tokens", "cached_tokens", "latency_s", "rollback_used",
    "rollback_verified", "rollback_checks", "test_runs", "memory_injected", "memory_injected_count", "error",
]


def parse_arm(arm: str) -> tuple[str | None, str]:
    """返回 (记忆版本, 成本模式)。v1 函数名硬过滤；v2 类别作用域；v3 类别 + 具体性闸门 + top-1。"""
    mem, _, cost = arm.partition("__")
    if mem.startswith("no_memory") or mem == "none":
        version = None
    elif mem in ("mem_v3", "memory_v3", "v3"):
        version = "v3"
    elif mem in ("mem_v2", "memory_v2", "v2"):
        version = "v2"
    else:
        version = "v1"
    return version, (cost or "baseline")


def src_identifiers(ws: Path) -> list[str]:
    """src 下的函数/类名——Agent 读过源码就能知道，不涉及 ground-truth。"""
    import ast
    ids: list[str] = []
    for p in (ws / "src").glob("*.py"):
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                ids.append(node.name)
    return sorted(set(ids))


def retrieval_hint(task: dict, ws: Path) -> str:
    """只用 Agent 可观察到的东西构造检索信号：源码文件名、函数名、可见测试名。"""
    files = [p.stem for p in (ws / "src").glob("*.py")]
    visible = (ws / "tests" / "test_visible.py").read_text()
    funcs = [w.replace("test_", "") for w in visible.split() if w.startswith("test_") or "test_" in w]
    words = " ".join(sorted(set(files)) + sorted(set(funcs)) + src_identifiers(ws))
    return words


def visible_failure(ws: Path) -> str:
    """跑一次可见测试，把失败输出作为 Agent 可观察的补充检索信号（非 ground-truth）。"""
    import os
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ws / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_visible.py"],
        cwd=str(ws), capture_output=True, text=True, env=env,
    )
    return (proc.stdout + "\n" + proc.stderr)[:1200]


def run_arm(cfg: LLMConfig, arm: str, tasks: list[dict], args) -> None:
    version, cost_name = parse_arm(arm)
    mode = cost_mode(cost_name)
    work_root = (Path(args.work_dir) if args.work_dir else ROOT / "experiments" / "work") / arm
    trace_root = (Path(args.trace_dir) if args.trace_dir else ROOT / "experiments" / "traces") / arm
    mem_path = (Path(args.memory_dir) if args.memory_dir else ROOT / "experiments" / "memory") / \
        f"{(args.label or arm)}.jsonl"
    mem_path.parent.mkdir(parents=True, exist_ok=True)
    memory = ReflectionMemory(mem_path, version=version) if version else None
    if args.reset_memory and mem_path.exists():
        mem_path.unlink()
        memory = ReflectionMemory(mem_path, version=version) if version else None

    done = set()
    if args.csv.exists() and not args.reset_memory:
        with open(args.csv) as f:
            for row in csv.DictReader(f):
                done.add((row["arm"], row["task_id"]))
    label = args.label or arm

    llm = LLMClient(cfg)
    consecutive_llm_errors = 0
    for i, task in enumerate(tasks, 1):
        if (label, task["id"]) in done:
            print(f"[{arm}] {i}/{len(tasks)} {task['id']} 已完成，跳过", flush=True)
            continue
        ws = work_root / task["id"]
        ckpt_dir = work_root / f"_ckpt_{task['id']}"
        for p in (ws, ckpt_dir):
            if p.exists():
                shutil.rmtree(p)
        shutil.copytree(workspace_of(task["id"], DATA_DIR), ws)
        tb = Toolbox(ws, cost=mode, tests_readonly=True, ckpt_dir=ckpt_dir)
        agent = ReactAgent(llm, tb, memory=memory, cost=mode, budget=Budget(
            max_steps=args.max_steps, wall_timeout_s=args.wall_timeout, max_total_tokens=args.max_tokens,
        ), trace_dir=trace_root)
        full_task = dict(task, retrieval_hint=retrieval_hint(task, ws),
                         src_identifiers=src_identifiers(ws),
                         visible_failure=visible_failure(ws))
        full_task["observed_categories"] = sorted(infer_categories(
            " ".join([full_task["prompt"], full_task["retrieval_hint"], full_task["visible_failure"]])))
        trace = trace_root / f"{task['id']}.txt"
        t0 = time.time()
        res = run_with_retry(agent, full_task, lambda: judge(task, ws), arm, trace)
        row = {
            "arm": label, "task_id": task["id"], "family": task["family"],
            "success": int(res.success), "judge_detail": res.judge_detail,
            "failure_mode": res.failure_mode or "", "steps": res.steps, "calls": res.calls,
            "tool_calls": res.tool_calls, "plan_calls": res.plan_calls, "reflect_calls": res.reflect_calls,
            "prompt_tokens": res.prompt_tokens, "completion_tokens": res.completion_tokens,
            "reflect_tokens": res.reflect_prompt_tokens + res.reflect_completion_tokens,
            "total_tokens": res.all_tokens, "cached_tokens": res.cached_tokens,
            "latency_s": res.latency_s, "rollback_used": res.rollback_used,
            "rollback_verified": int(res.rollback_verified), "rollback_checks": res.rollback_checks,
            "test_runs": res.test_runs,
            "memory_injected": "|".join(res.memory_injected), "memory_injected_count": res.memory_injected_count,
            "error": res.error,
        }
        write_row(args.csv, row)
        status = "PASS" if res.success else f"FAIL({res.failure_mode})"
        print(f"[{arm}] {i}/{len(tasks)} {task['id']} {status} steps={res.steps} "
              f"tok={row['total_tokens']} calls={res.calls} {round(time.time() - t0, 1)}s", flush=True)
        if res.failure_mode == "llm_error":
            consecutive_llm_errors += 1
            if consecutive_llm_errors >= 3:
                print("连续 3 次 LLM 故障，中止本 arm", flush=True)
                break
        else:
            consecutive_llm_errors = 0
        shutil.rmtree(ws, ignore_errors=True)
        shutil.rmtree(ckpt_dir, ignore_errors=True)
        if memory is not None:
            st = memory.state()
            extra = f" 闸门={st['gate']}" if st["version"] == "v3" else ""
            print(f"    记忆: {st['n_lessons']} 条 拒收={st['rejects']}{extra}", flush=True)


def write_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="no_memory__baseline,memory__baseline,memory__optimized")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--csv", type=Path, default=ROOT / "experiments" / "episodes.csv")
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--wall-timeout", type=int, default=240)
    ap.add_argument("--max-tokens", type=int, default=90000)
    ap.add_argument("--model", default="")
    ap.add_argument("--provider", default="")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--reset-memory", action="store_true")
    ap.add_argument("--tasks-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--trace-dir", default="")
    ap.add_argument("--memory-dir", default="")
    ap.add_argument("--work-dir", default="")
    ap.add_argument("--label", default="", help="CSV 里的臂名前缀（用于区分 v2 复跑）")
    ap.add_argument("--task-set", default="main", choices=["main", "all", "single", "multi"])
    ap.add_argument("--shuffle", action="store_true", help="用 --seed 固定种子打乱任务顺序（记忆在线累积时避免按族分块）")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    cfg = LLMConfig()
    if args.model:
        cfg.model = args.model
    if args.provider:
        cfg.provider = args.provider
    if args.base_url:
        cfg.base_url = args.base_url

    tasks = load_tasks(args.tasks_dir, None)
    missing = [t["id"] for t in tasks if not (workspace_of(t["id"], args.tasks_dir) / "src").exists()]
    if len(missing) == len(tasks):
        print("任务集为空，重建...", flush=True)
        from bench.tasks import build_tasks
        build_tasks(args.tasks_dir)
        tasks = load_tasks(args.tasks_dir, None)
    elif missing:
        print(f"部分任务缺 workspace（{len(missing)} 个），先运行 python -m bench.tasks 重建", file=sys.stderr)
        return 1
    if args.task_set == "main":
        tasks = select_main(tasks, seed=args.seed)
    elif args.task_set == "single":
        tasks = [t for t in tasks if t["kind"] == "single"]
    elif args.task_set == "multi":
        tasks = [t for t in tasks if t["kind"] == "multi"]
    if args.shuffle:
        import random
        random.Random(args.seed).shuffle(tasks)
    if args.limit:
        tasks = tasks[: args.limit]
    if not tasks:
        print("没有任务，先运行 python -m bench.tasks", file=sys.stderr)
        return 1
    print(f"模型={cfg.label()} 任务={len(tasks)} arms={args.arms}", flush=True)
    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        run_arm(cfg, arm, tasks, args)
    print("完成，结果:", args.csv, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
