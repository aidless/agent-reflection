"""阶段 1 分析：三臂成功率 / Wilson CI / McNemar / 注入率 / 按类别净差 / 聚类敏感性。

只读 CSV 与记忆 JSONL，不调用 LLM。用法：
  python3 -m bench.analyze_memory --csv no_memory.csv mem_v1.csv mem_v2.csv --out phase1.md
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.memory import CATEGORY_ZH, ReflectionMemory, infer_categories  # noqa: E402
from bench.tasks import load_tasks, workspace_of  # noqa: E402


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def mcnemar_exact(b: int, c: int) -> float:
    """双侧精确 McNemar：b/c 为两种不一致方向的任务数。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def mde(n: int, p: float = 0.5, alpha: float = 0.05, power: float = 0.8) -> float:
    """独立比例的正常近似 MDE（与上一轮 24.7pp 的口径一致）。"""
    z_a = 1.959964 if alpha == 0.05 else 1.644854
    z_b = 0.841621 if power == 0.8 else 1.281552
    if n <= 0:
        return 1.0
    return min(1.0, (z_a + z_b) * math.sqrt(2 * p * (1 - p) / n))


def read_rows(path: Path) -> dict[str, dict]:
    rows = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            if r.get("arm") and r.get("task_id"):
                rows[r["task_id"]] = r
    return rows


def as_int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def summarize(rows: dict[str, dict]) -> dict:
    n = len(rows)
    k = sum(as_int(r["success"]) for r in rows.values())
    lo, hi = wilson(k, n)
    step_vals = [as_int(r["steps"]) for r in rows.values()]
    calls = [as_int(r["calls"]) for r in rows.values()]
    tok = [as_int(r["total_tokens"]) for r in rows.values()]
    ep_tok = [as_int(r["prompt_tokens"]) + as_int(r["completion_tokens"]) for r in rows.values()]
    fails = Counter(r.get("failure_mode") or "none" for r in rows.values() if as_int(r["success"]) == 0)
    return {
        "n": n, "k": k, "rate": k / n if n else 0.0, "ci": (lo, hi),
        "steps": statistics.mean(step_vals) if step_vals else 0.0,
        "calls": statistics.mean(calls) if calls else 0.0,
        "tokens": statistics.mean(tok) if tok else 0.0,
        "episode_tokens": statistics.mean(ep_tok) if ep_tok else 0.0,
        "fail_modes": fails,
    }


def injected_stats(rows: dict[str, dict]) -> dict:
    hit = [r for r in rows.values() if as_int(r["memory_injected_count"]) > 0]
    total = sum(as_int(r["memory_injected_count"]) for r in rows.values())
    pass_hit = sum(1 for r in hit if as_int(r["success"]) == 1)
    fail_hit = len(hit) - pass_hit
    # 首次注入发生在执行顺序的第几题（CSV 顺序即执行顺序）
    first = None
    for i, r in enumerate(rows.values()):
        if as_int(r["memory_injected_count"]) > 0:
            first = i + 1
            break
    return {
        "tasks": len(rows), "hit_tasks": len(hit), "hit_rate": len(hit) / len(rows) if rows else 0.0,
        "injections": total, "pass_after": pass_hit, "fail_after": fail_hit,
        "first_hit_row": first,
    }


def src_ids(ws: Path) -> list[str]:
    ids = []
    for p in (ws / "src").glob("*.py"):
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                ids.append(node.name)
    return sorted(set(ids))


def audit_library(path: Path, version: str, tasks: list[dict], k: int = 3) -> dict:
    """离线审计：把已有记忆库固定，对 250 题逐题检索，统计真实可注入的题/条数。"""
    if not path.exists():
        return {"exists": False, "n_lessons": 0, "hit_tasks": 0, "injections": 0,
                "hit_rate": 0.0, "by_category": {}, "gate": {}, "chars_mean": 0.0}
    mem = ReflectionMemory(path, version=version)
    hit, total, by_cat, chars_sum = 0, 0, defaultdict(lambda: [0, 0]), 0
    for t in tasks:
        ws = workspace_of(t["id"])
        files = [p.stem for p in (ws / "src").glob("*.py")]
        visible = (ws / "tests" / "test_visible.py").read_text()
        hint = " ".join(sorted(set(files)) + [w for w in visible.split() if w.startswith("test_")] + src_ids(ws))
        ctx = dict(t, retrieval_hint=hint, src_identifiers=src_ids(ws),
                   observed_categories=sorted(infer_categories(" ".join([t["prompt"], hint]))))
        chosen, _ = mem.retrieve(ctx, k=k, max_chars=900)
        cat = t.get("bug_category", "")
        by_cat[cat][1] += 1
        if chosen:
            hit += 1
            total += len(chosen)
            chars_sum += mem.last_render_chars
            by_cat[cat][0] += 1
    return {
        "exists": True, "n_lessons": len(mem.lessons), "hit_tasks": hit, "injections": total,
        "hit_rate": hit / len(tasks) if tasks else 0.0,
        "by_category": {c: v for c, v in by_cat.items()},
        "categories": sorted({l.category for l in mem.lessons.values() if l.category}),
        "rejects": dict(mem.rejects),
        "gate": dict(mem.gate_stats),
        "chars_mean": chars_sum / total if total else 0.0,
    }


def variant_keys(task_id: str, family: str) -> list[str]:
    if task_id.startswith("multi-"):
        body = task_id[len("multi-"):]
        parts = body.split("-x-")
        return parts
    return [f"{family}-{task_id.split('-', 1)[1]}"]


def cluster_bootstrap(a: dict[str, dict], b: dict[str, dict], family_map: dict[str, str],
                      iters: int = 20000, seed: int = 11) -> dict:
    """按变体聚类：每个变体取包含它的任务的平均成功率，再对变体做 bootstrap。"""
    groups = defaultdict(list)
    for tid, row in a.items():
        if tid not in b:
            continue
        for key in variant_keys(tid, family_map.get(tid, "")):
            groups[key].append(tid)
    diffs = []
    for key, tids in groups.items():
        sa = statistics.mean(as_int(a[t]["success"]) for t in tids)
        sb = statistics.mean(as_int(b[t]["success"]) for t in tids)
        diffs.append(sb - sa)
    rng = random.Random(seed)
    boot = []
    n = len(diffs)
    for _ in range(iters):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        boot.append(statistics.mean(sample))
    boot.sort()
    lo, hi = boot[int(0.025 * iters)], boot[int(0.975 * iters)]
    p_left = sum(1 for x in boot if x <= 0) / iters
    p_right = sum(1 for x in boot if x >= 0) / iters
    p = min(1.0, 2 * min(p_left, p_right))
    return {"n_variants": n, "mean_diff": statistics.mean(diffs), "ci": (lo, hi), "p": p}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", nargs="+", required=True)
    ap.add_argument("--names", nargs="+", default=[])
    ap.add_argument("--memory-dir", nargs="+", default=[])
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    paths = [Path(p) for p in args.csv]
    names = args.names or [p.stem for p in paths]
    arms = {name: read_rows(p) for name, p in zip(names, paths)}
    tasks = load_tasks()
    family_map = {t["id"]: t["family"] for t in tasks}
    cat_map = {t["id"]: t.get("bug_category", "") for t in tasks}
    task_ids = [t["id"] for t in tasks]

    lines: list[str] = []
    lines.append("# 记忆实验结果（250 题对照）\n")
    n_max = max(len(r) for r in arms.values())
    lines.append(f"任务集 {len(tasks)} 题；每臂实际完成 n 见下表。未跑完的臂按实际 n 报告，不外推。\n")

    lines.append("## 1. 各臂总体\n")
    lines.append("| 臂 | n | 成功 | 成功率 | 95% Wilson CI | 平均步数 | 平均调用 | token/任务（含反思） | episode token/任务 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for name, rows in arms.items():
        s = summarize(rows)
        lines.append(
            f"| {name} | {s['n']} | {s['k']} | {fmt_pct(s['rate'])} | "
            f"{fmt_pct(s['ci'][0])}–{fmt_pct(s['ci'][1])} | {s['steps']:.1f} | {s['calls']:.1f} | "
            f"{s['tokens']:.0f} | {s['episode_tokens']:.0f} |")
    lines.append("")

    base_name = "no_memory" if "no_memory" in arms else names[0]
    base_tok = summarize(arms[base_name])["tokens"] if base_name in arms else 0.0
    for name in names:
        if "v3" not in name or name not in arms or not base_tok:
            continue
        tok = summarize(arms[name])["tokens"]
        delta = tok / base_tok - 1
        verdict = "PASS" if delta <= 0.10 else "FAIL（超出预注册的 +10% 上限）"
        lines.append(f"### 1b. token 硬约束（{name} vs {base_name}）\n")
        lines.append(f"- 平均 token/任务：{tok:.0f} vs {base_tok:.0f}，变化 **{delta * 100:+.1f}%**；"
                     f"预注册上限 +10.0% -> **{verdict}**。\n")

    lines.append("## 2. 注入率（真实计数）\n")
    lines.append("| 臂 | 命中题数/n | 注入条数 | 注入后成功 | 注入后失败 | 首次注入出现在第几题 |")
    lines.append("|---|---|---|---|---|---|")
    for name, rows in arms.items():
        st = injected_stats(rows)
        if st["injections"] == 0:
            lines.append(f"| {name} | 0/{st['tasks']} | 0 | 0 | 0 | 机制未生效（无可注入教训） |")
        else:
            lines.append(f"| {name} | {st['hit_tasks']}/{st['tasks']} ({fmt_pct(st['hit_rate'])}) | "
                         f"{st['injections']} | {st['pass_after']} | {st['fail_after']} | {st['first_hit_row']} |")
    lines.append("")

    if args.memory_dir:
        mdirs = [Path(d) for d in args.memory_dir]
        lines.append("### 2b. 离线检索审计（固定记忆库，不调用 LLM）\n")
        lines.append("| 库 | 版本 | 教训数 | 可命中题/n | 可注入条数 | 平均注入字数 | 闸门拒收 | 类别覆盖 | 写入拒收 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for name, rows in arms.items():
            if "v3" in name:
                version = "v3"
            elif "v2" in name:
                version = "v2"
            elif "v1" in name:
                version = "v1"
            else:
                continue
            path = None
            for d in mdirs:
                for fn in (f"{name}.jsonl", f"{name}__baseline.jsonl"):
                    if (d / fn).exists():
                        path = d / fn
                        break
                if path:
                    break
            if path is None:  # 找不到就按约定指向第一个目录，audit 会返回 exists=False
                path = mdirs[0] / f"{name}__baseline.jsonl"
            au = audit_library(path, version, tasks)
            lines.append(f"| {name} | {version} | {au['n_lessons']} | {au['hit_tasks']}/{len(tasks)} "
                         f"({fmt_pct(au['hit_rate'])}) | {au['injections']} | {au.get('chars_mean', 0):.0f} | "
                         f"{au.get('gate', {}) or '-'} | "
                         f"{','.join(au.get('categories', [])) or '-'} | {au.get('rejects', {})} |")
        lines.append("")
        lines.append("> 离线审计是用**最终记忆库**对全量任务的事后估计（不含 visible_failure），"
                     "不是在线注入的真实值；在线值受执行顺序影响，见第 2 节。\n")

    lines.append("## 3. 配对 McNemar（任务级）\n")
    lines.append("| 对比 | n 对 | 仅 A 成功 | 仅 B 成功 | 不一致数 | p | 该 n 的 80% power MDE |")
    lines.append("|---|---|---|---|---|---|---|")
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            pairs.append((names[i], names[j]))
    for na, nb in pairs:
        common = [t for t in task_ids if t in arms[na] and t in arms[nb]]
        b = sum(1 for t in common if as_int(arms[na][t]["success"]) == 1 and as_int(arms[nb][t]["success"]) == 0)
        c = sum(1 for t in common if as_int(arms[na][t]["success"]) == 0 and as_int(arms[nb][t]["success"]) == 1)
        p = mcnemar_exact(b, c)
        lines.append(f"| {na} vs {nb} | {len(common)} | {b} | {c} | {b + c} | {p:.4f} | ±{mde(len(common)) * 100:.1f}pp |")
    lines.append("")
    lines.append(f"> MDE 为独立比例正常近似（p=0.5, α=0.05, power=0.8）；n={n_max} 时约 ±{mde(n_max) * 100:.1f}pp。")
    lines.append("> 组合任务复用 65 个变体，任务级 McNemar 会低估方差；第 6 节给按变体聚类的敏感性分析。\n")

    lines.append("## 4. 按 bug_category 净差（记忆臂 vs no_memory）\n")
    base = "no_memory" if "no_memory" in arms else names[0]
    for name in names:
        if name == base:
            continue
        rows = arms[name]
        lines.append(f"### {name} vs {base}\n")
        lines.append("| 类别 | n | 记忆臂胜 | 记忆臂负 | 持平 | 净差 |")
        lines.append("|---|---|---|---|---|---|")
        for cat in sorted(set(cat_map.values())):
            common = [t for t in task_ids if t in rows and t in arms[base] and cat_map.get(t) == cat]
            w = sum(1 for t in common if as_int(rows[t]["success"]) == 1 and as_int(arms[base][t]["success"]) == 0)
            l = sum(1 for t in common if as_int(rows[t]["success"]) == 0 and as_int(arms[base][t]["success"]) == 1)
            net = w - l
            lines.append(f"| {cat} ({CATEGORY_ZH.get(cat, '')}) | {len(common)} | {w} | {l} | "
                         f"{len(common) - w - l} | {net:+d} |")
        lines.append("")

    lines.append("## 5. 注入归因（注入题在配对比较里的方向）\n")
    for name in names:
        if name == base:
            continue
        rows = arms[name]
        hit = [t for t in rows if as_int(rows[t]["memory_injected_count"]) > 0 and t in arms[base]]
        if not hit:
            lines.append(f"- **{name}**：注入 0 次，无法归因（机制未生效）。")
            continue
        w = sum(1 for t in hit if as_int(rows[t]["success"]) == 1 and as_int(arms[base][t]["success"]) == 0)
        l = sum(1 for t in hit if as_int(rows[t]["success"]) == 0 and as_int(arms[base][t]["success"]) == 1)
        same = len(hit) - w - l
        lines.append(f"- **{name}**：注入题 {len(hit)} 道；相对 no_memory：走对 {w}、走错 {l}、持平 {same}；"
                     f"净差 {w - l:+d}（命中题内 McNemar p={mcnemar_exact(w, l):.4f}）。")
    lines.append("")

    lines.append("## 6. 聚类敏感性（按变体，bootstrap 20000 次）\n")
    lines.append("| 对比 | 变体数 | 平均成功率差 (B−A) | 95% CI | p（双侧 bootstrap） |")
    lines.append("|---|---|---|---|---|")
    for na, nb in pairs:
        cb = cluster_bootstrap(arms[na], arms[nb], family_map)
        lines.append(f"| {nb} vs {na} | {cb['n_variants']} | {cb['mean_diff'] * 100:+.1f}pp | "
                     f"{cb['ci'][0] * 100:+.1f}pp–{cb['ci'][1] * 100:+.1f}pp | {cb['p']:.4f} |")
    lines.append("")

    lines.append("## 7. 样本量需求（要分辨本轮这个量级，需要多少样本）\n")
    base_rows = arms.get(base, {})
    for name in names:
        if name == base:
            continue
        rows = arms[name]
        common = [t for t in task_ids if t in rows and t in base_rows]
        delta = (sum(as_int(rows[t]["success"]) for t in common) -
                 sum(as_int(base_rows[t]["success"]) for t in common)) / len(common)
        disc = sum(1 for t in common
                   if as_int(rows[t]["success"]) != as_int(base_rows[t]["success"])) / len(common)
        if delta <= 0:
            lines.append(f"- **{name} vs {base}**：观测差 {delta * 100:+.1f}pp（非正），"
                         f"不存在“需要多少样本才能分辨正收益”的问题；本轮方向不支持记忆臂。")
            continue
        # 配对 McNemar：n ≈ (z_a+z_b)^2 * 不一致率 / δ^2
        n_paired = (1.959964 + 0.841621) ** 2 * max(disc, 1e-6) / (delta ** 2)
        # 独立比例：n ≈ (z_a+z_b)^2 * 2p(1-p) / δ^2（p=0.5）
        n_indep = (1.959964 + 0.841621) ** 2 * 0.5 / (delta ** 2)
        lines.append(f"- **{name} vs {base}**：观测差 {delta * 100:+.1f}pp，不一致率 {fmt_pct(disc)}；"
                     f"配对设计约需 **{math.ceil(n_paired)}** 对，独立比例设计约需 **{math.ceil(n_indep)}**/臂。")
    lines.append("> 这是按本轮不一致率做的点估计，不是承诺；组合题共享 65 个变体，"
                 "单纯把任务数堆到上述数字不会增加独立信息，必须同时增加独立变体。\n")

    lines.append("## 8. 失败模式\n")
    for name, rows in arms.items():
        s = summarize(rows)
        modes = ", ".join(f"{k}={v}" for k, v in sorted(s["fail_modes"].items())) or "无"
        lines.append(f"- **{name}**：{modes}")
    lines.append("")

    text = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
