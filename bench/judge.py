"""判定器：隐藏测试 + 可见测试一起跑；测试文件始终用任务原始版本，防止被改写。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .tasks import DATA_DIR

IGNORE = {".agent_ckpt", ".agent_tmp", "__pycache__", ".pytest_cache"}


def _ignore(dirpath: str, names: list[str]) -> list[str]:
    return [n for n in names if n in IGNORE]


def judge(task: dict, workspace: Path, timeout_s: int = 45) -> tuple[bool, str]:
    task_dir = DATA_DIR / task["id"]
    with tempfile.TemporaryDirectory(prefix="judge-") as td:
        tmp = Path(td)
        shutil.copytree(workspace, tmp / "repo", ignore=_ignore)
        repo = tmp / "repo"
        # 用原始可见测试覆盖，防止 Agent 改测试
        pristine = task_dir / "workspace" / "tests" / "test_visible.py"
        (repo / "tests").mkdir(parents=True, exist_ok=True)
        shutil.copy2(pristine, repo / "tests" / "test_visible.py")
        (repo / "tests" / "test_hidden.py").write_text(task["hidden_tests"])
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                cwd=str(repo), env=env, capture_output=True, text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return False, f"判定超时({timeout_s}s)"
        out = (proc.stdout + proc.stderr).strip()
        summary = ""
        for line in out.splitlines():
            if re.search(r"(passed|failed|error)", line, re.I):
                summary = line.strip()
        detail = summary[:300] if summary else out[-300:]
        return proc.returncode == 0, detail


def judge_with_reference(task: dict) -> tuple[bool, str]:
    """自检：把参考解写入临时工作区后判定，必须通过。"""
    with tempfile.TemporaryDirectory(prefix="ref-") as td:
        ws = Path(td) / "ws"
        shutil.copytree(DATA_DIR / task["id"] / "workspace", ws)
        for rel, content in task["reference"].items():
            (ws / rel).parent.mkdir(parents=True, exist_ok=True)
            (ws / rel).write_text(content)
        return judge(task, ws)
