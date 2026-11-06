"""自检：每个任务必须有缺陷版失败、参考解通过，且可见测试确实暴露缺陷。"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .judge import judge, judge_with_reference
from .tasks import DATA_DIR, build_tasks, load_tasks


def check(task: dict) -> dict:
    ws = DATA_DIR / task["id"] / "workspace"
    ok_buggy, detail = judge(task, ws)
    ref_ok, ref_detail = judge_with_reference(task)
    # 可见测试在有缺陷的仓库里应当失败
    import os, subprocess, sys
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ws / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_visible.py"],
        cwd=str(ws), capture_output=True, text=True, env=env,
    )
    return {
        "id": task["id"],
        "buggy_judge": ok_buggy,
        "reference_judge": ref_ok,
        "visible_fails_on_buggy": proc.returncode != 0,
        "detail": detail,
        "ref_detail": ref_detail,
    }


def main() -> int:
    build_tasks()
    tasks = load_tasks()
    bad = []
    for t in tasks:
        r = check(t)
        status = "OK" if (not r["buggy_judge"] and r["reference_judge"] and r["visible_fails_on_buggy"]) else "BAD"
        print(f"{status} {r['id']:28s} buggy_pass={r['buggy_judge']} ref_pass={r['reference_judge']} "
              f"visible_fails={r['visible_fails_on_buggy']} | {r['detail'][:70]}")
        if status == "BAD":
            bad.append(r)
    print(f"\n共 {len(tasks)} 个任务，异常 {len(bad)} 个")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
