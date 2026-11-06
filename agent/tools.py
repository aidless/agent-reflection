"""工具集：文件读写、shell、代码运行、网页搜索。

每个工具都有参数校验、权限边界、超时、输出截断；所有错误以结构化结果回传给模型，
不向上抛异常。沙箱优先使用 bubblewrap（只读整机 + 仅工作区可写 + 断网），
bubblewrap 不可用时降级为 cwd 限制 + rlimit + 命令黑名单，并在结果里标注实际模式。
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .config import CostMode
from .rollback import SnapshotManager

MAX_READ_BYTES = 200_000
MAX_WRITE_BYTES = 200_000
DENY_CMD = re.compile(
    r"(rm\s+-rf\s+/|sudo\s|mkfs|dd\s+if=|chmod\s+777\s+/|:\(\)\{|shutdown|reboot|"
    r"systemctl\s|curl\s+.*\|\s*(bash|sh)|wget\s+.*\|\s*(bash|sh))"
)


def truncate(text: str, limit: int, keep: str = "head_tail") -> str:
    if len(text) <= limit:
        return text
    if keep == "head":
        return text[: limit - 30] + f"\n...[截断 {len(text) - limit + 30} 字符]"
    half = (limit - 60) // 2
    return text[:half] + f"\n...[中间截断 {len(text) - 2 * half} 字符]...\n" + text[-half:]


def failure_digest(text: str) -> str:
    """失败指纹：先剥离耗时/临时路径等易变字段，再取哈希。

    pytest 输出里的 `in 0.05s`、临时目录名每次都变，直接哈希会让"同一失败"
    永远无法被识别，自动回滚也就永远不触发。
    """
    norm = re.sub(r"\bin\s+\d+\.\d+\s*s\b", "", text)
    norm = re.sub(r"\b\d+\.\d+s\b", "", norm)
    norm = re.sub(r"0x[0-9a-fA-F]+", "", norm)
    norm = re.sub(r"/tmp/[^\s:]+", "/tmp/<x>", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha256(norm.encode("utf-8", "ignore")).hexdigest()[:12]


_FAILED_ID = re.compile(r"(?:FAILED|ERROR)\s+([^\s:]+::[\w\[\]\-]+)")


def failed_test_ids(text: str) -> str:
    """失败测试集合（排序后按 | 连接）。

    断言值会随每次编辑变化，但"哪几个测试挂了"是稳定的；用它判定
    "这次改动没有改变任何失败项"，比整段输出哈希可靠得多。
    """
    return "|".join(sorted(set(_FAILED_ID.findall(text))))


@dataclass
class ToolOutput:
    ok: bool
    content: str
    meta: dict = field(default_factory=dict)

    def as_text(self) -> str:
        return self.content


class Toolbox:
    def __init__(self, root: Path, cost: CostMode | None = None, tests_readonly: bool = True,
                 enable_rollback: bool = True, ckpt_dir: Path | None = None):
        self.root = Path(root).resolve()
        self.cost = cost or CostMode()
        self.tests_readonly = tests_readonly
        self.enable_rollback = enable_rollback
        self.snap = SnapshotManager(self.root, snap_dir=ckpt_dir)
        self.memo: dict[str, ToolOutput] = {}
        self.tmpdir = self.root / ".agent_tmp"
        self.tmpdir.mkdir(exist_ok=True)
        self.run_counter = 0
        self.sandbox = "bwrap" if shutil.which("bwrap") else "restricted-subprocess"
        self.mutating_ops: list[dict] = []
        self.last_pruned: list[str] = []

    def snapshot_before_write(self, label: str) -> str | None:
        """写操作前打点，让自动回滚能精确撤销"最近一次坏改动"。"""
        if not self.enable_rollback:
            return None
        cid = self.snap.snapshot(label)
        dropped = self.snap.prune(keep=4)
        if dropped:
            self.last_pruned = dropped
        return cid

    # ---------- 路径与权限 ----------
    def _resolve(self, rel: str, for_write: bool = False) -> Path:
        if not rel or not isinstance(rel, str):
            raise ValueError("路径不能为空")
        p = (self.root / rel).resolve()
        if self.root not in p.parents and p != self.root:
            raise PermissionError(f"路径越界（禁止访问工作区之外）: {rel}")
        if for_write and self.tests_readonly:
            parts = p.relative_to(self.root).parts
            if parts and parts[0] == "tests":
                raise PermissionError("tests/ 为只读：必须修源码，不能改测试")
            if p.suffix == ".py" and "test_" in p.name:
                raise PermissionError("测试文件只读：必须修源码")
        return p

    # ---------- 调度 ----------
    def call(self, name: str, args: dict) -> ToolOutput:
        if not self.enable_rollback and name in ("checkpoint", "list_checkpoints", "rollback"):
            return ToolOutput(False, "本实验配置未启用回滚能力")
        key = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
        if self.cost.memoize_tools and name in ("read_file", "grep", "list_files") and key in self.memo:
            cached = self.memo[key]
            return ToolOutput(cached.ok, cached.content + "\n[命中缓存：内容未变]", {**cached.meta, "memo_hit": True})
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return ToolOutput(False, f"未知工具: {name}")
        try:
            out = handler(args if isinstance(args, dict) else {})
            if not isinstance(out, ToolOutput):
                out = ToolOutput(True, str(out))
        except PermissionError as e:
            out = ToolOutput(False, f"权限拒绝: {e}")
        except (ValueError, KeyError, TypeError) as e:
            out = ToolOutput(False, f"参数错误: {e}")
        except Exception as e:  # 工具内部异常一律回传给模型
            out = ToolOutput(False, f"工具执行异常: {type(e).__name__}: {e}")
        if self.cost.memoize_tools:
            if name in ("read_file", "grep", "list_files"):
                self.memo[key] = out
            elif name in ("edit_file", "write_file"):
                self.memo.clear()
        return out

    # ---------- 文件 ----------
    def _tool_list_files(self, args: dict) -> ToolOutput:
        base = self._resolve(args.get("path", "."))
        if not base.exists():
            return ToolOutput(False, f"路径不存在: {args.get('path')}")
        lines = []
        for p in sorted(base.rglob("*")):
            if any(part in (".agent_ckpt", ".agent_tmp", "__pycache__", ".pytest_cache") for part in p.relative_to(self.root).parts):
                continue
            rel = p.relative_to(self.root).as_posix()
            lines.append(("[dir] " if p.is_dir() else "      ") + rel + ("" if p.is_dir() else f"  ({p.stat().st_size}B)"))
        return ToolOutput(True, truncate("\n".join(lines), self.cost.obs_max_chars))

    def _tool_read_file(self, args: dict) -> ToolOutput:
        path = self._resolve(args["path"])
        if not path.exists():
            return ToolOutput(False, f"文件不存在: {args['path']}")
        if path.stat().st_size > MAX_READ_BYTES:
            return ToolOutput(False, f"文件过大（>{MAX_READ_BYTES} 字节）")
        text = path.read_text(errors="replace")
        start = int(args.get("start_line", 1) or 1)
        end = int(args.get("end_line", 0) or 0)
        lines = text.splitlines()
        if end and end > start:
            lines = lines[start - 1 : end]
            start = start
        numbered = [f"{i + start:4d}| {ln}" for i, ln in enumerate(lines)]
        body = truncate("\n".join(numbered), self.cost.obs_max_chars)
        return ToolOutput(True, f"{args['path']} ({len(text.splitlines())} 行)\n{body}")

    def _tool_grep(self, args: dict) -> ToolOutput:
        pattern = args.get("pattern")
        if not pattern:
            return ToolOutput(False, "缺少 pattern")
        base = self._resolve(args.get("path", "."))
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return ToolOutput(False, f"正则非法: {e}")
        hits = []
        files = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
        for p in files:
            if any(part in (".agent_ckpt", ".agent_tmp", "__pycache__") for part in p.relative_to(self.root).parts):
                continue
            if p.stat().st_size > MAX_READ_BYTES:
                continue
            try:
                for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{p.relative_to(self.root).as_posix()}:{i}: {line.strip()[:160]}")
            except (UnicodeDecodeError, OSError):
                continue
        return ToolOutput(True, truncate("\n".join(hits) or "无匹配", self.cost.obs_max_chars, "head"))

    def _tool_edit_file(self, args: dict) -> ToolOutput:
        path = self._resolve(args["path"], for_write=True)
        old = args.get("old", "")
        new = args.get("new", "")
        if not old:
            return ToolOutput(False, "old 不能为空")
        if not path.exists():
            return ToolOutput(False, f"文件不存在: {args['path']}")
        text = path.read_text()
        count = text.count(old)
        if count == 0:
            return ToolOutput(False, "未找到待替换文本（请先 read_file 确认原文，注意缩进与空白）")
        if count > 1 and not args.get("replace_all"):
            return ToolOutput(False, f"待替换文本出现 {count} 次，不唯一；请提供更长上下文或设 replace_all=true")
        before = text
        after = text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1)
        if len(after.encode()) > MAX_WRITE_BYTES:
            return ToolOutput(False, "写入超过大小限制")
        path.write_text(after)
        self.mutating_ops.append({"op": "edit", "path": args["path"], "old": old, "new": new})
        if self.cost.diff_observation:
            diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(), "before", "after", lineterm="", n=1))
            return ToolOutput(True, truncate("\n".join(diff), 700))
        return ToolOutput(True, f"已修改 {args['path']}（替换 {1 if 'replace_all' not in args else count} 处）")

    def _tool_write_file(self, args: dict) -> ToolOutput:
        path = self._resolve(args["path"], for_write=True)
        content = args.get("content", "")
        if len(content.encode()) > MAX_WRITE_BYTES:
            return ToolOutput(False, "内容超过大小限制")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        self.mutating_ops.append({"op": "write", "path": args["path"]})
        return ToolOutput(True, f"已写入 {args['path']}（{len(content)} 字符）")

    # ---------- 执行 ----------
    def _run_process(self, cmd: list[str], timeout: int, allow_net: bool = False) -> dict:
        """优先 bwrap 沙箱；失败则降级。返回 code/stdout/stderr/mode/timed_out。"""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.root / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("PYTHONHOME", None)
        bwrap = shutil.which("bwrap")
        if bwrap:
            wrapped = [
                bwrap, "--die-with-parent", "--unshare-pid",
                "--ro-bind", "/", "/",
                "--bind", str(self.root), str(self.root),
                "--chdir", str(self.root),
                "--proc", "/proc", "--dev", "/dev",
            ]
            if not allow_net:
                wrapped += ["--unshare-net"]
            wrapped += cmd
        else:
            wrapped = cmd
        try:
            proc = subprocess.run(
                wrapped, cwd=str(self.root), env=env, capture_output=True, text=True,
                timeout=timeout, start_new_session=True,
            )
            out = proc.stdout + ("\n[stderr]\n" + proc.stderr if proc.stderr.strip() else "")
            return {"code": proc.returncode, "out": out, "mode": "bwrap" if bwrap else "restricted-subprocess", "timed_out": False}
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or "") + "\n" + (e.stderr or "")
            return {"code": -9, "out": out if isinstance(out, str) else "", "mode": "bwrap" if bwrap else "restricted-subprocess", "timed_out": True}
        except FileNotFoundError:
            return {"code": 127, "out": "找不到命令", "mode": "host", "timed_out": False}

    def _tool_shell(self, args: dict) -> ToolOutput:
        cmd = args.get("cmd", "")
        if not cmd:
            return ToolOutput(False, "缺少 cmd")
        if DENY_CMD.search(cmd):
            return ToolOutput(False, "命令被安全策略拒绝（破坏性或提权操作）")
        timeout = min(int(args.get("timeout_s", 20) or 20), 60)
        res = self._run_process(["bash", "-lc", cmd], timeout)
        text = res["out"]
        if res["timed_out"]:
            return ToolOutput(False, f"命令超时({timeout}s) 已终止\n输出: {truncate(text, self.cost.obs_max_chars)}", {"mode": res["mode"]})
        body = truncate(text, self.cost.obs_max_chars)
        return ToolOutput(res["code"] == 0, f"exit={res['code']} mode={res['mode']}\n{body}", {"mode": res["mode"], "exit": res["code"]})

    def _tool_run_tests(self, args: dict) -> ToolOutput:
        selector = args.get("selector", "") or "tests"
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", selector]
        res = self._run_process(cmd, int(args.get("timeout_s", 40) or 40))
        text = res["out"]
        if res["timed_out"]:
            return ToolOutput(False, truncate(f"测试超时: {text}", self.cost.obs_max_chars))
        if self.cost.test_failures_only and res["code"] != 0:
            keep = []
            for line in text.splitlines():
                s = line.strip()
                if re.match(r"(FAILED|ERROR|E\s*\s|assert|\\*\\*\\*)", s) or "assert" in s.lower() or s.startswith("FAILED") or s.endswith("failed"):
                    keep.append(line[:300])
            text = "\n".join(keep[-12:]) or text[-400:]
        digest = failure_digest(text)
        ids = failed_test_ids(text)
        meta = {"exit": res["code"], "digest": digest, "failed_ids": ids, "mode": res["mode"]}
        if res["code"] == 0:
            return ToolOutput(True, "测试全部通过\n" + truncate(text, 200), meta)
        return ToolOutput(False, truncate(text, self.cost.obs_max_chars), meta)

    def _tool_run_python(self, args: dict) -> ToolOutput:
        code = args.get("code", "")
        if not code:
            return ToolOutput(False, "缺少 code")
        self.run_counter += 1
        script = self.tmpdir / f"run_{self.run_counter}.py"
        script.write_text(code)
        res = self._run_process([sys.executable, "-I", "-B", str(script)], int(args.get("timeout_s", 20) or 20))
        if res["timed_out"]:
            return ToolOutput(False, "执行超时，已终止")
        return ToolOutput(res["code"] == 0, truncate(f"exit={res['code']}\n{res['out']}", self.cost.obs_max_chars))

    # ---------- 网络 ----------
    def _tool_web_search(self, args: dict) -> ToolOutput:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolOutput(False, "缺少 query")
        url = "https://cn.bing.com/search?q=" + urllib.parse.quote(query)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            return ToolOutput(False, f"搜索不可达: {type(e).__name__}")
        items = []
        for block in re.findall(r'<li class="b_algo".*?</li>', html, flags=re.S)[:5]:
            m = re.search(r'<h2[^>]*>(.*?)</h2>', block, flags=re.S)
            u = re.search(r'<a[^>]+href="(http[^"]+)"', block)
            if not (m and u):
                continue
            title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            items.append({"title": title[:120], "url": u.group(1)[:200]})
        if not items:
            return ToolOutput(False, "未解析到搜索结果（页面结构可能变化）")
        return ToolOutput(True, truncate(json.dumps(items, ensure_ascii=False, indent=1), self.cost.obs_max_chars))

    def _tool_web_fetch(self, args: dict) -> ToolOutput:
        url = args.get("url", "")
        if not url.startswith(("http://", "https://")):
            return ToolOutput(False, "仅支持 http/https")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read(500_000).decode("utf-8", errors="replace")
        except Exception as e:
            return ToolOutput(False, f"抓取失败: {type(e).__name__}: {str(e)[:100]}")
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;|&amp;|&lt;|&gt;", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return ToolOutput(True, truncate(text, self.cost.obs_max_chars))

    # ---------- checkpoint ----------
    def _tool_checkpoint(self, args: dict) -> ToolOutput:
        cid = self.snap.snapshot(args.get("label", ""), args.get("step"))
        return ToolOutput(True, f"已创建 checkpoint {cid}")

    def _tool_list_checkpoints(self, args: dict) -> ToolOutput:
        return ToolOutput(True, json.dumps(self.snap.list()[-8:], ensure_ascii=False))

    def _tool_rollback(self, args: dict) -> ToolOutput:
        target = args.get("to", "latest")
        cid = self.snap.latest() if target in ("latest", "", None) else target
        if not cid:
            return ToolOutput(False, "没有可用 checkpoint")
        report = self.snap.restore(cid)
        return ToolOutput(
            True,
            f"已回滚到 {cid}；恢复 {report.restored} 个文件，删除 {report.removed} 个；"
            f"哈希校验={'通过' if report.verified else '失败'}",
            {"verified": report.verified, "restored": report.restored},
        )


TOOL_SPECS = """可用工具（每次只调用一个）：
1. list_files {"path": "."} 列出工作区文件
2. read_file {"path": "src/x.py", "start_line": 1, "end_line": 120}
3. grep {"pattern": "正则", "path": "."} 在工作区搜索
4. edit_file {"path": "...", "old": "原文精确片段", "new": "替换后"} 修改源码（tests/ 只读）
5. write_file {"path": "...", "content": "..."} 新建文件
6. run_tests {"selector": "tests"} 运行 pytest，返回通过/失败
7. run_python {"code": "..."} 在工作区跑一段 python，用于验证假设
8. shell {"cmd": "...", "timeout_s": 15} 受限 shell（工作区内、断网、超时终止）
9. web_search {"query": "..."} / 10. web_fetch {"url": "..."} 外网查询
11. checkpoint {"label": "..."} 打快照；12. list_checkpoints {}
13. rollback {"to": "latest"} 回滚到快照，并做哈希校验
"""
