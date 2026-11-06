"""从 episodes CSV 生成实验结果：累计成功率曲线、A/B 表、成本对比、显著性检验。

用法:
    python -m bench.report --csv experiments/main_*.csv --out experiments
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for p in paths:
        if not p.exists():
            continue
        with open(p) as f:
            for r in csv.DictReader(f):
                r["success"] = int(r["success"])
                for k in ("total_tokens", "calls", "steps", "tool_calls", "reflect_tokens",
                          "cached_tokens", "latency_s", "rollback_used", "rollback_verified",
                          "rollback_checks", "test_runs", "memory_injected_count"):
                    try:
                        r[k] = float(r[k]) if k == "latency_s" else int(r[k] or 0)
                    except (TypeError, ValueError):
                        r[k] = 0
                rows.append(r)
    return rows


def cum_curve(successes: list[int]) -> list[float]:
    out, s = [], 0
    for i, x in enumerate(successes, 1):
        s += x
        out.append(s / i)
    return out


def bootstrap_ci(successes: list[int], n: int = 5000, seed: int = 0) -> tuple[float, float]:
    if not successes:
        return 0.0, 0.0
    rng = random.Random(seed)
    k = len(successes)
    means = []
    for _ in range(n):
        means.append(sum(successes[rng.randrange(k)] for _ in range(k)) / k)
    means.sort()
    return means[int(0.025 * n)], means[int(0.975 * n)]


def mcnemar(pairs: list[tuple[int, int]]) -> dict:
    """配对 McNemar 检验：只有两臂结果不一致的样本计入。"""
    b = sum(1 for a, c in pairs if a == 1 and c == 0)   # A 赢
    c_ = sum(1 for a, c in pairs if a == 0 and c == 1)  # B 赢
    n = b + c_
    if n == 0:
        return {"b": b, "c": c_, "p": 1.0, "n_discordant": 0}
    # 精确二项检验（双尾）
    p = 0.0
    for i in range(0, n + 1):
        prob = math.comb(n, i) * (0.5 ** n)
        if prob <= math.comb(n, b) * (0.5 ** n) + 1e-12:
            p += prob
    return {"b": b, "c": c_, "p": min(1.0, p), "n_discordant": n}


def mde_power(n: int, alpha: float = 0.05) -> float:
    """近似可检测的最小差异（两个独立比例、80% 功效、p≈0.5 的最坏情形）。"""
    z_a, z_b = 1.96, 0.84
    return (z_a + z_b) * math.sqrt(2 * 0.25 / n) if n else 1.0


def summarize(rows: list[dict]) -> dict:
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)
    out = {}
    for arm, rs in by_arm.items():
        succ = [r["success"] for r in rs]
        tok = [r["total_tokens"] for r in rs]
        calls = [r["calls"] for r in rs]
        steps = [r["steps"] for r in rs]
        out[arm] = {
            "n": len(rs),
            "success_rate": sum(succ) / len(succ) if succ else 0.0,
            "successes": sum(succ),
            "ci": bootstrap_ci(succ),
            "tokens_mean": sum(tok) / len(tok) if tok else 0,
            "tokens_median": sorted(tok)[len(tok) // 2] if tok else 0,
            "calls_mean": sum(calls) / len(calls) if calls else 0,
            "steps_mean": sum(steps) / len(steps) if steps else 0,
            "cached_tokens_mean": sum(r["cached_tokens"] for r in rs) / len(rs),
            "latency_mean": sum(r["latency_s"] for r in rs) / len(rs),
            "fail_modes": dict(sorted(
                {m: sum(1 for r in rs if r["failure_mode"] == m) for m in {r["failure_mode"] for r in rs}}.items()
            )),
            "memory_injected_mean": sum(r["memory_injected_count"] for r in rs) / len(rs),
        }
    return out


def arm_map(rows: list[dict]) -> dict[str, dict[str, dict]]:
    m: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        m[r["arm"]][r["task_id"]] = r
    return m


def paired(m: dict, a: str, b: str) -> list[tuple[int, int]]:
    common = sorted(set(m.get(a, {})) & set(m.get(b, {})))
    return [(m[a][t]["success"], m[b][t]["success"]) for t in common]


def plot_curves(rows: list[dict], out: Path) -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except ImportError:
        return None

    names = {f.name for f in font_manager.fontManager.ttflist}
    for cand in ("Noto Sans CJK SC", "Noto Serif CJK SC", "AR PL UMing TW MBE", "WenQuanYi Zen Hei"):
        if cand in names:
            plt.rcParams["font.family"] = cand
            break
    plt.rcParams["axes.unicode_minus"] = False

    order: list[str] = []
    for r in rows:
        if r["task_id"] not in order:
            order.append(r["task_id"])
    by_arm: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rows:
        by_arm[r["arm"]][r["task_id"]] = r["success"]

    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    colors = {"no_memory__baseline": "#9aa0a6", "memory__baseline": "#1a73e8", "memory__optimized": "#188038"}
    for arm, res in by_arm.items():
        xs = [t for t in order if t in res]
        ys = cum_curve([res[t] for t in xs])
        ax.plot(range(1, len(ys) + 1), ys, label=arm, color=colors.get(arm), linewidth=2)
    ax.set_xlabel("任务序号（按实验执行顺序）")
    ax.set_ylabel("累计成功率")
    ax.set_title("累计成功率曲线（同任务集、同模型、同预算）")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right")
    ax.set_ylim(0, 1.0)
    p = out / "success_curve.png"
    fig.tight_layout()
    fig.savefig(p)
    plt.close(fig)
    return p


def plot_cost(rows: list[dict], out: Path) -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except ImportError:
        return None

    names = {f.name for f in font_manager.fontManager.ttflist}
    for cand in ("Noto Sans CJK SC", "Noto Serif CJK SC", "AR PL UMing TW MBE", "WenQuanYi Zen Hei"):
        if cand in names:
            plt.rcParams["font.family"] = cand
            break
    plt.rcParams["axes.unicode_minus"] = False

    arms = sorted({r["arm"] for r in rows})
    succ_tok = [[r["total_tokens"] for r in rows if r["arm"] == a and r["success"]] for a in arms]
    fail_tok = [[r["total_tokens"] for r in rows if r["arm"] == a and not r["success"]] for a in arms]
    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=150)
    positions = range(len(arms))
    ax.boxplot([x or [0] for x in succ_tok], positions=[p - 0.15 for p in positions],
               widths=0.28, patch_artist=True,
               boxprops=dict(facecolor="#188038", alpha=0.6))
    ax.boxplot([x or [0] for x in fail_tok], positions=[p + 0.15 for p in positions],
               widths=0.28, patch_artist=True,
               boxprops=dict(facecolor="#d93025", alpha=0.5))
    ax.set_xticks(list(positions))
    ax.set_xticklabels(arms, fontsize=8)
    ax.set_ylabel("每任务 token 数")
    ax.set_title("每任务 token 分布（绿=成功，红=失败）")
    ax.grid(alpha=0.3, axis="y")
    p = out / "cost_box.png"
    fig.tight_layout()
    fig.savefig(p)
    plt.close(fig)
    return p


def family_table(rows: list[dict]) -> str:
    """按任务族 × 臂的成功率 / 步数 / token 三元对照。"""
    fams = sorted({r["family"] for r in rows})
    arms = sorted({r["arm"] for r in rows})
    by = defaultdict(list)
    for r in rows:
        by[(r["family"], r["arm"])].append(r)
    lines = ["| 任务族 | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    for f in fams:
        cells = []
        for a in arms:
            rs = by.get((f, a), [])
            if not rs:
                cells.append("-")
                continue
            succ = sum(r["success"] for r in rs)
            tok = sum(r["total_tokens"] for r in rs) / len(rs)
            steps = sum(r["steps"] for r in rs) / len(rs)
            cells.append(f"{succ}/{len(rs)} · {tok / 1000:.1f}k · {steps:.0f}步")
        lines.append(f"| {f} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def load_lessons(memory_dir: Path, arm: str) -> dict[str, dict]:
    """读取某臂的 append-only 记忆，重建 {lesson_id: 最新状态}。"""
    candidates = [Path(memory_dir) / f"{arm}.jsonl", ROOT / "experiments" / "memory_v2" / f"{arm}.jsonl"]
    path = next((p for p in candidates if p.exists()), candidates[0])
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") == "add":
            d = rec["lesson"]
            out[d["id"]] = d
        elif rec.get("type") == "feedback" and rec.get("id") in out:
            k = "success_after" if rec.get("outcome") == "success" else "fail_after"
            out[rec["id"]][k] = out[rec["id"]].get(k, 0) + 1
    return out


def task_identifiers(task_id: str) -> set[str]:
    """该任务源码里的函数/类名（与 runner 构造检索信号的方式一致）。"""
    from .tasks import DATA_DIR, workspace_of

    ws = workspace_of(task_id, DATA_DIR) / "src"
    ids: set[str] = set()
    if not ws.exists():
        return ids
    import ast
    for p in ws.glob("*.py"):
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                ids.add(node.name)
    return ids


def classify_harm(case: dict, lessons: dict[str, dict], ids: set[str], base_row: dict | None) -> tuple[str, str]:
    """判定：无注入 / 检索污染 / 写入污染 / 上下文稀释。返回 (类别, 证据)。"""
    inj = [x for x in (case.get("injected") or case.get("memory_injected") or "").split("|") if x]
    if not inj:
        return "无注入（与记忆无关）", "检索未命中任何教训"
    mismatched = []
    for lid in inj:
        ls = lessons.get(lid)
        if not ls:
            continue
        scope = set(ls.get("scope") or [])
        if scope and ids and not (scope & ids):
            mismatched.append(f"{lid} 的作用域 {sorted(scope)[:3]} 不在本任务函数集合内")
    if mismatched:
        return "检索污染", "；".join(mismatched[:2])
    bad = [lid for lid in inj if (lessons.get(lid, {}).get("fail_after", 0) >
                                  lessons.get(lid, {}).get("success_after", 0))]
    if bad:
        return "写入污染", f"{bad[0]} 历史反馈失败 {lessons[bad[0]]['fail_after']} 次 > 成功 {lessons[bad[0]]['success_after']} 次"
    if case.get("failure_mode") == "stuck_reading":
        return "上下文稀释", "触发只读护栏，历史被裁剪后反复重读同一文件"
    if base_row and base_row["calls"]:
        per_call = case["total_tokens"] / max(1, case["calls"])
        base_per_call = base_row["total_tokens"] / max(1, base_row["calls"])
        if per_call > base_per_call * 1.3:
            return "上下文稀释", f"每调用 token {per_call:.0f} vs 基线 {base_per_call:.0f}（+{per_call / base_per_call - 1:.0%}）"
    return "未归因（需人工看 trace）", f"注入 {len(inj)} 条，失败模式 {case.get('failure_mode')}"


def memory_harm_cases(rows: list[dict], baseline_arm: str = "no_memory__baseline",
                      memory_dir: Path | None = None) -> list[dict]:
    """记忆臂失败但无记忆臂成功的任务——用于定位检索污染。"""
    m = arm_map(rows)
    base = m.get(baseline_arm, {})
    memory_dir = memory_dir or (ROOT / "experiments" / "memory")
    out = []
    for arm in m:
        if arm == baseline_arm:
            continue
        lessons = load_lessons(memory_dir, arm)
        for tid, r in m[arm].items():
            if tid in base and base[tid]["success"] == 1 and r["success"] == 0:
                ids = task_identifiers(tid)
                b = dict(base[tid])
                cause, evidence = classify_harm(r, lessons, ids, b)
                out.append({"arm": arm, "task_id": tid, "family": r["family"],
                            "failure_mode": r["failure_mode"], "steps": r["steps"],
                            "tokens": r["total_tokens"],
                            "injected": r.get("memory_injected", ""),
                            "injected_count": r.get("memory_injected_count", 0),
                            "cause": cause, "evidence": evidence,
                            "rules": [lessons[l]["rule"] for l in (r.get("memory_injected") or "").split("|")
                                      if l in lessons][:2]})
    return out


def memory_write_stats(memory_dir: Path, arm: str) -> dict:
    """统计记忆写入：新增 / 合并 / 拒收原因。用于解释"为什么记忆臂没学到东西"。"""
    path = Path(memory_dir) / f"{arm}.jsonl"
    out = {"add": 0, "merge": 0, "reject": defaultdict(int)}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = rec.get("type")
        if t == "add":
            out["add"] += 1
        elif t == "merge":
            out["merge"] += 1
        elif t == "reject":
            out["reject"][rec.get("reason", "?")] += 1
    return out


def write_markdown(rows: list[dict], summary: dict, out: Path) -> Path:
    arms = list(summary)
    md = ["## A/B 结果（同任务、同模型、同预算）\n",
          "| 臂 | 样本 | 成功率 | 95% CI | token/任务 | calls/任务 | 平均步数 |",
          "|---|---|---|---|---|---|---|"]
    for a, s in summary.items():
        lo, hi = s["ci"]
        md.append(f"| {a} | {s['n']} | {s['success_rate']:.1%} ({s['successes']}/{s['n']}) | "
                  f"{lo:.1%}–{hi:.1%} | {s['tokens_mean']:.0f} | {s['calls_mean']:.1f} | {s['steps_mean']:.1f} |")

    md += ["", "### 配对 McNemar\n"]
    m = arm_map(rows)
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            pairs = paired(m, arms[i], arms[j])
            if not pairs:
                continue
            st = mcnemar(pairs)
            md.append(f"- {arms[i]} vs {arms[j]}: n={len(pairs)}，不一致 {st['n_discordant']} "
                      f"(A 赢 {st['b']} / B 赢 {st['c']})，p={st['p']:.3f}，"
                      f"该样本量可检测的最小差异≈{mde_power(len(pairs)):.1%}")

    md += ["", "### 按任务族（成功数 · 平均 token · 平均步数）\n", family_table(rows)]
    md += ["", "### 记忆的净效果（相对无记忆臂，按任务族）\n"]
    m_all = arm_map(rows)
    for arm in arms:
        if arm == "no_memory__baseline":
            continue
        md.append(f"\n**{arm}**\n")
        md.append("| 任务族 | 记忆臂 胜 | 记忆臂 负 | 持平 | 净变化 |")
        md.append("|---|---|---|---|---|")
        for f in sorted({r["family"] for r in rows}):
            win = lose = tie = 0
            for tid, r in m_all.get(arm, {}).items():
                if r["family"] != f or tid not in m_all.get("no_memory__baseline", {}):
                    continue
                b = m_all["no_memory__baseline"][tid]["success"]
                if r["success"] and not b:
                    win += 1
                elif b and not r["success"]:
                    lose += 1
                else:
                    tie += 1
            if win or lose:
                md.append(f"| {f} | {win} | {lose} | {tie} | {win - lose:+d} |")

    cases = memory_harm_cases(rows)
    if cases:
        md += ["", "### 记忆臂失败 / 无记忆臂成功的任务（归因）\n",
               "| 臂 | 任务 | 失败模式 | 步数 | 注入 | 归因 | 证据 |",
               "|---|---|---|---|---|---|---|"]
        for c in cases:
            md.append(f"| {c['arm']} | {c['task_id']} | {c['failure_mode']} | {c['steps']} | "
                      f"{c['injected_count']} | {c['cause']} | {c['evidence']} |")
        for c in cases:
            if c["rules"]:
                md.append(f"\n- `{c['task_id']}` 注入的教训原文：")
                for r in c["rules"]:
                    md.append(f"  - {r[:220]}")

    md += ["", "### 回滚可观测性（自然任务）\n",
           "| 臂 | 进入回滚判定次数 | 真正执行回滚 | 哈希校验通过 | 平均 run_tests/任务 | test_runs≥2 的任务 |",
           "|---|---|---|---|---|---|"]
    for a in arms:
        rs = [r for r in rows if r["arm"] == a]
        md.append(f"| {a} | {sum(r['rollback_checks'] for r in rs)} | "
                  f"{sum(r['rollback_used'] for r in rs)} | {sum(r['rollback_verified'] for r in rs)} | "
                  f"{sum(r.get('test_runs', 0) for r in rs) / len(rs):.1f} | "
                  f"{sum(1 for r in rs if r.get('test_runs', 0) >= 2)} |")
    md += ["", "> 回滚只在“测试失败（写操作后）→ 编辑 → 再测试，且失败测试集合完全一致”时触发。"
           "自然任务集里 Agent 平均只跑 1.x 次测试就耗尽步数，这是回滚次数为 0 的结构性原因；"
           "分支本身由 `bench/rollback_probe.py` 的受控任务验证可执行（见 README）。"]

    mem_dir = out / "memory"
    if mem_dir.exists():
        md += ["", "### 记忆写入统计（写入侧）\n", "| 臂 | 新增 | 合并 | 拒收原因 |", "|---|---|---|---|"]
        for a in arms:
            if a.startswith("no_memory"):
                continue
            st = memory_write_stats(mem_dir, a)
            rej = ", ".join(f"{k}={v}" for k, v in sorted(st["reject"].items())) or "-"
            md.append(f"| {a} | {st['add']} | {st['merge']} | {rej} |")

    p = out / "report.md"
    p.write_text("\n".join(md) + "\n")
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", nargs="+", required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "experiments")
    args = ap.parse_args()

    paths = [Path(c) if Path(c).is_absolute() else ROOT / c for c in args.csv]
    rows = read_rows(paths)
    if not rows:
        print("没有数据")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)

    summary = summarize(rows)
    m = arm_map(rows)

    print(f"样本: {len(rows)} 条 episode，arms={list(summary)}\n")
    print("| arm | n | 成功率 | 95% CI | token/任务 | calls/任务 | 步数 | 失败模式 |")
    print("|---|---|---|---|---|---|---|---|")
    for arm, s in summary.items():
        lo, hi = s["ci"]
        modes = ", ".join(f"{k or 'none'}={v}" for k, v in s["fail_modes"].items() if k)
        print(f"| {arm} | {s['n']} | {s['success_rate']:.1%} ({s['successes']}/{s['n']}) | "
              f"{lo:.1%}–{hi:.1%} | {s['tokens_mean']:.0f} | {s['calls_mean']:.1f} | "
              f"{s['steps_mean']:.1f} | {modes} |")

    print("\n配对 McNemar（同任务、同模型、同预算）:")
    arms = list(summary)
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            a, b = arms[i], arms[j]
            pairs = paired(m, a, b)
            if not pairs:
                continue
            st = mcnemar(pairs)
            print(f"  {a} vs {b}: n={len(pairs)} 不一致={st['n_discordant']} "
                  f"(A赢={st['b']}, B赢={st['c']}) p={st['p']:.3f} "
                  f"MDE(n={len(pairs)},80%功效)≈{mde_power(len(pairs)):.1%}")

    base, opt = "memory__baseline", "memory__optimized"
    if base in summary and opt in summary:
        bt, ot = summary[base]["tokens_mean"], summary[opt]["tokens_mean"]
        cut = (1 - ot / bt) if bt else 0
        print(f"\n成本: {base} {bt:.0f} tok/任务 -> {opt} {ot:.0f} tok/任务，降幅 {cut:.1%}")
        print(f"成功率: {summary[base]['success_rate']:.1%} -> {summary[opt]['success_rate']:.1%}")

    # 按族统计
    print("\n按族成功率:")
    fam: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        fam[r["family"]][r["arm"]].append(r["success"])
    for f in sorted(fam):
        parts = [f"{a}={sum(v) / len(v):.0%}({len(v)})" for a, v in sorted(fam[f].items())]
        print(f"  {f}: " + ", ".join(parts))

    (args.out / "summary.json").write_text(json.dumps(
        {"summary": summary, "n_rows": len(rows)}, ensure_ascii=False, indent=2))

    p1 = plot_curves(rows, args.out)
    p2 = plot_cost(rows, args.out)
    p3 = write_markdown(rows, summary, args.out)
    print(f"\n图: {p1}, {p2}\n报告: {p3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
