"""checkpoint 与回滚：文件系统快照 + 哈希清单校验，回滚后可证明状态一致。"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

EXCLUDE_DIRS = {".agent_ckpt", ".agent_tmp", "__pycache__", ".pytest_cache", ".git"}
EXCLUDE_SUFFIX = {".pyc", ".pyo"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_manifest(root: Path) -> dict[str, str]:
    """相对路径 -> sha256，排除快照目录与缓存。"""
    manifest: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if any(part in EXCLUDE_DIRS for part in p.relative_to(root).parts):
            continue
        if p.suffix in EXCLUDE_SUFFIX:
            continue
        manifest[rel] = _sha256(p)
    return manifest


@dataclass
class RestoreReport:
    checkpoint_id: str
    before: dict[str, str]
    after: dict[str, str]
    restored: int
    removed: int
    verified: bool
    diff: list[str]

    def as_dict(self) -> dict:
        return {
            "checkpoint_id": self.checkpoint_id,
            "restored": self.restored,
            "removed": self.removed,
            "verified": self.verified,
            "diff": self.diff[:10],
        }


class SnapshotManager:
    """每个 checkpoint 是一份完整文件树副本；回滚后逐文件比对哈希。

    snap_dir 可以指向工作区之外：快照目录若放在工作区内，Agent 用 shell/find
    就能读到"修改前的源码"，既是信息泄漏，也会把步骤浪费在翻快照上
    （实测一次失败任务里 4/12 步用于 diff .agent_ckpt）。
    """

    def __init__(self, root: Path, snap_dir: Path | None = None):
        self.root = Path(root)
        self.dir = Path(snap_dir) if snap_dir else self.root / ".agent_ckpt"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.oplog = self.dir / "oplog.jsonl"

    def _snap_dir(self, cid: str) -> Path:
        return self.dir / cid / "files"

    def snapshot(self, label: str = "", step: int | None = None) -> str:
        cid = f"ckpt-{time.time_ns()}"
        target = self._snap_dir(cid)
        target.mkdir(parents=True, exist_ok=True)
        manifest = scan_manifest(self.root)
        for rel in manifest:
            src = self.root / rel
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        meta = {
            "id": cid,
            "label": label,
            "step": step,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "files": manifest,
        }
        (self.dir / cid / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        self._log({"event": "snapshot", "id": cid, "label": label, "step": step, "n_files": len(manifest)})
        return cid

    def list(self) -> list[dict]:
        items = []
        for d in sorted(self.dir.glob("ckpt-*")):
            meta = d / "meta.json"
            if meta.exists():
                m = json.loads(meta.read_text())
                items.append({"id": m["id"], "label": m.get("label", ""), "step": m.get("step")})
        return items

    def latest(self) -> str | None:
        items = self.list()
        return items[-1]["id"] if items else None

    def prune(self, keep: int = 4) -> list[str]:
        """只保留最近 keep 个 checkpoint，更早的丢弃并写入 oplog（可观测）。"""
        items = self.list()
        dropped = []
        for m in (items[:-keep] if keep > 0 else items):
            shutil.rmtree(self.dir / m["id"], ignore_errors=True)
            dropped.append(m["id"])
            self._log({"event": "discard", "id": m["id"], "label": m.get("label", ""),
                       "step": m.get("step")})
        return dropped

    def restore(self, cid: str) -> RestoreReport:
        src = self._snap_dir(cid)
        meta_path = self.dir / cid / "meta.json"
        if not src.exists() or not meta_path.exists():
            raise FileNotFoundError(f"checkpoint 不存在: {cid}")
        expected: dict[str, str] = json.loads(meta_path.read_text())["files"]
        before = scan_manifest(self.root)

        removed = 0
        for rel in before:
            if rel not in expected:
                (self.root / rel).unlink()
                removed += 1
        restored = 0
        for rel, digest in expected.items():
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, dst)
            if _sha256(dst) != digest:
                raise RuntimeError(f"回滚校验失败: {rel}")
            restored += 1

        after = scan_manifest(self.root)
        diff = sorted(set(after) ^ set(expected)) + [k for k in expected if after.get(k) != expected[k]]
        verified = after == expected
        report = RestoreReport(cid, before, after, restored, removed, verified, diff)
        self._log({"event": "restore", "id": cid, "restored": restored, "removed": removed, "verified": verified})
        return report

    def _log(self, record: dict) -> None:
        with open(self.oplog, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
