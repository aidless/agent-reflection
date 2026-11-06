"""实验 CSV 完整性校验：行数、id 对齐、缺失/重复/多余。

用法:
  python3 -m bench.check_runs experiments/v2/no_memory.csv experiments/v2/mem_v1.csv experiments/v2/mem_v2.csv
退出码 0 表示三份 CSV 与任务集完全对齐；非 0 表示有问题（会打印缺失/多余 id）。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.tasks import load_tasks  # noqa: E402

REQUIRED = ["arm", "task_id", "family", "success", "steps", "calls", "total_tokens",
            "latency_s", "memory_injected_count"]


def check(path: Path, expected: set[str]) -> tuple[bool, dict]:
    rows = list(csv.DictReader(open(path)))
    ids = [r.get("task_id", "") for r in rows]
    info = {
        "file": str(path),
        "physical_lines": sum(1 for _ in open(path)),
        "logical_rows": len(rows),
        "unique_ids": len(set(ids)),
    }
    problems = []
    missing_cols = [c for c in REQUIRED if rows and c not in rows[0]]
    if missing_cols:
        problems.append(f"缺列: {missing_cols}")
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        problems.append(f"重复 id {len(dups)}: {dups[:5]}")
    missing = sorted(expected - set(ids))
    extra = sorted(set(ids) - expected)
    if missing:
        problems.append(f"缺失 {len(missing)}: {missing[:5]}")
    if extra:
        problems.append(f"多余 {len(extra)}: {extra[:5]}")
    bad_success = [r["task_id"] for r in rows if r.get("success") not in ("0", "1")]
    if bad_success:
        problems.append(f"success 非 0/1: {bad_success[:5]}")
    info["problems"] = problems
    return not problems, info


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    expected = {t["id"] for t in load_tasks()}
    all_ok = True
    id_sets = {}
    print(f"任务集: {len(expected)} 个 id")
    for arg in sys.argv[1:]:
        ok, info = check(Path(arg), expected)
        id_sets[info["file"]] = None if info["problems"] else "aligned"
        print(f"- {info['file']}: 物理行 {info['physical_lines']}, CSV 行 {info['logical_rows']}, "
              f"唯一 id {info['unique_ids']} -> {'OK' if ok else 'FAIL'}")
        for p in info["problems"]:
            print(f"    ! {p}")
        all_ok &= ok
    if all_ok:
        print("结论: 三份 CSV 均与任务集逐一对齐，无缺失/重复/多余。")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
