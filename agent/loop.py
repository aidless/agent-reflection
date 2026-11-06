"""ReAct 循环：思考 -> 工具 -> 观察 -> 再思考。

包含：最大步数、墙钟超时、token 预算、死循环检测、重复动作检测、自动回滚、
子目标分解、按开关启用上下文裁剪与早停。
"""
from __future__ import annotations

import json
import os
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from .config import Budget, CostMode
from .llm import LLMClient, LLMError, Usage
from .memory import ReflectionMemory, normalize_category
from .tools import TOOL_SPECS, Toolbox

DEBUG_GUARD = os.environ.get("AGENT_DEBUG_GUARD", "") == "1"

SYSTEM_TEMPLATE = """你是修复 Python 小型仓库缺陷的工程 Agent。
工作区: {ws}
规则:
- 只能读写工作区内的文件；tests/ 与 test_*.py 只读，必须修源码而不是改测试。
- 隐藏测试覆盖边界情况，只让可见测试通过不算修好，要修根因。
- 每次只输出一个 JSON 对象，不要输出任何其他文字。
- 格式: {{"thought":"简要推理","action":"工具名","args":{{...}}}}
- 完成: {{"thought":"...","action":"finish","args":{{"summary":"改了什么"}}}}

{specs}
子目标（规划器给出，可调整）:
{subgoals}
{memory}
"""

PLAN_PROMPT = """把下面这个修 bug 任务拆成 2-4 个可验证的子目标，只输出 JSON：
{{"subgoals":["1. ...","2. ..."]}}
任务: {prompt}
工作区文件: {files}
"""

REFLECT_PROMPT = """分析一次失败的 Agent 执行，产出可迁移的结构化教训。
只输出一个 JSON 对象，不要推理过程。

任务: {prompt}
执行轨迹:
{trajectory}
最终判定: {judge_detail}

字段必须具体、可执行，不要空话：
{{"scenario":"什么场景/什么特征","error_type":"错误类别","root_cause":"根因","fix_pattern":"下次的具体做法","rule":"下次遇到X就做Y"}}

硬性要求：root_cause 或 fix_pattern 里必须出现本任务中真实存在的函数名/文件名/命令名
（例如 clamp、parse_range、src/calc.py、pytest）。只写"要仔细/别改测试/别只满足可见测试"
这类复述系统提示的教训会被直接丢弃，不写入记忆。
"""

REFLECT_PROMPT_V2 = """分析一次失败的 Agent 执行，产出可迁移的 bug 类别级教训。
只输出一个 JSON 对象，不要推理过程。

任务: {prompt}
执行轨迹:
{trajectory}
最终判定: {judge_detail}

字段必须具体、可执行，不要空话：
{{"bug_category":"从 boundary_compare / paging_index / reduce_init / mutable_default / cache_state / parsing_robustness / recursion_base / type_conversion 中选最贴切的一个",
"symptom":"测试是怎么失败的（可观察症状）","root_cause":"根因，具体到函数/语句",
"fix_pattern":"下次遇到同类症状的具体做法","language_constraints":"适用语言/库约束，如 Python3 纯标准库",
"rule":"下次遇到X就做Y"}}

不要求出现本任务的函数名：教训按 bug 类别迁移到其他任务。但根因必须指向具体代码行为，
只写"要仔细/别改测试/别只满足可见测试"这类复述系统提示的教训会被直接丢弃。
"""

# 首轮被推理文本挤爆预算时，用更短的输入重试一次
REFLECT_PROMPT_V3 = """分析一次失败的 Agent 执行，产出可迁移、可验证的 bug 类别级教训。
只输出一个 JSON 对象，不要推理过程。

任务: {prompt}
执行轨迹:
{trajectory}
最终判定: {judge_detail}

这条教训会被注入到别的任务，必须同时满足下面三条，缺一条就输出 {{"bug_category":"no_category"}}：
(a) 点名具体符号/函数/参数/条件（例如 clamp、hi、n <= 0、"空列表"），不能只写"边界情况"；
(b) 给出可验证判据（例如"输入 [] 应返回 []"、"last_page(0) 应返回 0"），不能只写"要小心"；
(c) bug_category 必须是下列之一：boundary_compare / paging_index / reduce_init /
    mutable_default / cache_state / parsing_robustness / recursion_base / type_conversion

输出字段（每项尽量 ≤60 字）：
{{"bug_category":"...","symptom":"测试怎么失败的","root_cause":"根因，具体到函数/语句",
"fix_pattern":"下次的具体做法，必须含可验证判据","language_constraints":"Python3 纯标准库等约束",
"rule":"下次遇到X就做Y"}}
"""

# 首轮被推理文本挤爆预算时，用更短的输入重试一次
REFLECT_RETRY_PROMPT = """直接输出 JSON，第一个字符必须是 {{，不要推理、不要解释。
失败任务: {prompt}
失败判定: {judge_detail}
执行摘要:
{summary}
字段(每项≤60字): scenario, error_type, root_cause, fix_pattern, rule"""

REFLECT_RETRY_PROMPT_V2 = """直接输出 JSON，第一个字符必须是 {{，不要推理、不要解释。
失败任务: {prompt}
失败判定: {judge_detail}
执行摘要:
{summary}
字段(每项≤60字): bug_category, symptom, root_cause, fix_pattern, language_constraints, rule"""

REFLECT_RETRY_PROMPT_V3 = """直接输出 JSON，第一个字符必须是 {{，不要推理、不要解释。
失败任务: {prompt}
失败判定: {judge_detail}
执行摘要:
{summary}
字段(每项≤60字): bug_category, symptom, root_cause, fix_pattern（必须含"输入X应返回Y"式判据）, language_constraints, rule
没有具体符号或可验证判据时输出 {{"bug_category":"no_category"}}"""



@dataclass
class EpisodeResult:
    task_id: str
    arm: str
    success: bool = False
    judge_detail: str = ""
    steps: int = 0
    calls: int = 0
    tool_calls: int = 0
    plan_calls: int = 0
    reflect_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reflect_prompt_tokens: int = 0
    reflect_completion_tokens: int = 0
    cached_tokens: int = 0
    latency_s: float = 0.0
    failure_mode: str = ""
    rollback_used: int = 0
    rollback_verified: bool = False
    rollback_checks: int = 0  # 进入"同一失败重复"判定分支的次数（可观测性）
    test_runs: int = 0        # 本 episode 调用 run_tests 的次数（回滚能否触发的前提）
    memory_injected: list[str] = field(default_factory=list)
    memory_injected_count: int = 0
    subgoals: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def all_tokens(self) -> int:
        return self.total_tokens + self.reflect_prompt_tokens + self.reflect_completion_tokens


def extract_action(text: str) -> dict | None:
    """从模型输出里抽取第一个含 action 的平衡 JSON 对象。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.lstrip("json")
    candidates = []
    depth = 0
    start = None
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : i + 1])
                start = None
    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "action" in obj:
            return obj
    return None


def extract_json_any(text: str) -> dict | None:
    """抽取第一个可解析的平衡 JSON 对象（不要求含 action 字段，用于反思结果）。"""
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1] if text.count("```") >= 2 else text
        text = text.lstrip("json").lstrip()
    depth, start, in_str, esc = 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    obj = json.loads(text[start: i + 1])
                except json.JSONDecodeError:
                    start = None
                    continue
                if isinstance(obj, dict):
                    return obj
                start = None
    return None


class ReactAgent:
    def __init__(
        self,
        llm: LLMClient,
        toolbox: Toolbox,
        memory: ReflectionMemory | None = None,
        cost: CostMode | None = None,
        budget: Budget | None = None,
        trace_dir: Path | None = None,
    ):
        self.llm = llm
        self.toolbox = toolbox
        self.memory = memory
        self.cost = cost or CostMode()
        self.budget = budget or Budget()
        self.trace_dir = Path(trace_dir) if trace_dir else None
        self.usage = Usage()

    # ---------- prompt ----------
    def _plan(self, task: dict) -> list[str]:
        n_src = len([p for p in (self.toolbox.root / "src").glob("*.py")]) if (self.toolbox.root / "src").exists() else 0
        if self.cost.planner_skip_max_files and n_src <= self.cost.planner_skip_max_files:
            return ["直接定位失败测试对应的源码，修复后跑全量测试"]
        files = ", ".join(sorted(p.relative_to(self.toolbox.root).as_posix() for p in (self.toolbox.root / "src").glob("*.py")))
        try:
            text, u = self.llm.chat(
                [{"role": "user", "content": PLAN_PROMPT.format(prompt=task["prompt"], files=files)}],
                max_tokens=200,
            )
            self.usage.add(u)
            obj = extract_action(text) or {}
            subs = obj.get("subgoals")
            if not subs:
                m = json.loads(text[text.find("{"): text.rfind("}") + 1]) if "{" in text else {}
                subs = m.get("subgoals", [])
            if isinstance(subs, list) and subs:
                return [str(s)[:120] for s in subs[:4]]
        except (LLMError, json.JSONDecodeError, ValueError):
            pass
        return ["复现失败测试", "定位并修根因", "跑全量测试确认"]

    # ---------- 反思 ----------
    def _reflect(self, task: dict, trajectory: list[str], judge_detail: str, version: str = "v1") -> tuple[dict | None, Usage, str]:
        """两段式反思：完整轨迹一次，解析失败则用压缩摘要重试一次。

        解析失败时不写记忆，避免垃圾教训污染检索。返回 (教训, 用量, 诊断信息)。
        """
        usage = Usage()
        traj = "\n".join(trajectory[-8:])[:2000]
        prompt_tpl = {"v1": REFLECT_PROMPT, "v2": REFLECT_PROMPT_V2, "v3": REFLECT_PROMPT_V3}[version]
        prompt = prompt_tpl.format(
            prompt=task["prompt"][:500], trajectory=traj, judge_detail=judge_detail[:400],
        )
        last_text = ""
        try:
            text, u = self.llm.chat([{"role": "user", "content": prompt}], max_tokens=900)
            usage.add(u)
            obj = extract_json_any(text)
            if isinstance(obj, dict) and obj.get("root_cause"):
                return obj, usage, ""
            last_text = text
        except LLMError as e:
            return None, usage, f"reflect_llm_error: {e}"

        # 重试：只给最后 6 步的一行摘要，减少模型推理空间
        steps = [l for l in trajectory if l.startswith("[step") or l.strip().startswith(("动作", "观察"))]
        summary = "\n".join(s.strip()[:100] for s in steps[-6:])
        retry_tpl = {"v1": REFLECT_RETRY_PROMPT, "v2": REFLECT_RETRY_PROMPT_V2,
                     "v3": REFLECT_RETRY_PROMPT_V3}[version]
        retry_prompt = retry_tpl.format(
            prompt=task["prompt"][:250], judge_detail=judge_detail[:200], summary=summary,
        )
        try:
            text2, u2 = self.llm.chat([{"role": "user", "content": retry_prompt}], max_tokens=500)
            usage.add(u2)
            obj = extract_json_any(text2)
            if isinstance(obj, dict) and obj.get("root_cause"):
                return obj, usage, "reflection_retry_ok"
            return None, usage, f"reflection_parse_failed: {last_text[:200]} || {text2[:200]}"
        except LLMError as e:
            return None, usage, f"reflect_retry_llm_error: {e}"

    # ---------- 主循环 ----------
    def run(self, task: dict, judge_fn, arm: str = "", trace_path: Path | None = None) -> EpisodeResult:
        res = EpisodeResult(task_id=task["id"], arm=arm)
        t0 = time.time()
        self.usage = Usage()
        self.toolbox.snap.snapshot("episode-start")

        subgoals = self._plan(task)
        res.subgoals = subgoals
        res.plan_calls = self.usage.calls
        res.prompt_tokens = self.usage.prompt_tokens
        res.completion_tokens = self.usage.completion_tokens

        memory_text, injected = "", []
        if self.memory is not None:
            lessons, memory_text = self.memory.retrieve(task, k=self.cost.memory_topk, max_chars=self.cost.memory_max_chars)
            injected = [l.id for l in lessons]
        res.memory_injected = injected
        res.memory_injected_count = len(injected)

        system = SYSTEM_TEMPLATE.format(
            ws=self.toolbox.root, specs=TOOL_SPECS,
            subgoals="\n".join(f"  {i + 1}. {s}" for i, s in enumerate(subgoals)),
            memory=(memory_text + "\n") if memory_text else "",
        )
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": task["prompt"] + f"\n最多 {self.budget.max_steps} 步，工作区: {self.toolbox.root}"}]
        trajectory: list[str] = [f"task: {task['prompt']}"]
        early: list[str] = []  # 被上下文裁剪掉的历史压缩成短摘要
        read_targets: set[str] = set()
        read_streak = 0
        repeat_counts: dict[str, int] = {}
        last_test_digest = None
        last_fail_ids, writes_since_test = "", 0
        judged: tuple[bool, str] | None = None
        abort_reason = ""

        for step in range(1, self.budget.max_steps + 1):
            if time.time() - t0 > self.budget.wall_timeout_s:
                res.failure_mode = "budget_time"
                break
            if self.usage.total_tokens > self.budget.max_total_tokens:
                res.failure_mode = "budget_tokens"
                break
            res.steps = step
            try:
                text, u = self.llm.chat(messages, max_tokens=self.cost.max_output_tokens)
                self.usage.add(u)
            except LLMError as e:
                res.failure_mode = "llm_error"
                res.error = str(e)[:200]
                break

            action = extract_action(text)
            if action is None:
                observation = "无法解析：请只输出一个 JSON 对象，包含 thought/action/args。"
                trajectory.append(f"[step {step}] 解析失败：{text[:120]}")
                messages += [{"role": "assistant", "content": text[:400]},
                             {"role": "user", "content": observation}]
                continue

            name = str(action.get("action", ""))
            args = action.get("args") or {}
            if not isinstance(args, dict):
                args = {"value": args}
            thought = str(action.get("thought", ""))[:200]
            key = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
            repeat_counts[key] = repeat_counts.get(key, 0) + 1
            if name == "read_file":
                # 只统计"重读同一个文件"：多模块仓库里逐文件通读是正常行为，
                # 读 7 个不同文件不该被判成卡死（这正是优化臂误杀的原因）。
                target = str(args.get("path", ""))
                read_streak = read_streak + 1 if target in read_targets else 0
                read_targets.add(target)
            elif name in ("grep", "list_files"):
                read_streak = 0
            else:
                read_streak = 0
            trajectory.append(f"[step {step}] 思考: {thought}\n  动作: {name} {json.dumps(args, ensure_ascii=False)[:200]}")

            if name == "finish":
                judged = judge_fn()
                trajectory.append(f"  判定: {judged[1][:200]}")
                break

            # 写操作前打点：自动回滚时能精确撤销最近一次坏改动
            if name in ("edit_file", "write_file") and self.toolbox.enable_rollback:
                cid = self.toolbox.snapshot_before_write(f"pre-write-step{step}")
                writes_since_test += 1
                if DEBUG_GUARD:
                    trajectory.append(f"  [ckpt] step={step} 保存 {cid} 丢弃={self.toolbox.last_pruned}")

            out = self.toolbox.call(name, args)
            res.tool_calls += 1
            if name == "run_tests":
                res.test_runs += 1
            observation = out.as_text()[: self.cost.obs_max_chars]
            trajectory.append(f"  观察: {observation[:300]}")

            # 死循环检测
            if repeat_counts[key] >= 3:
                observation += "\n[护栏] 同一动作已重复 3 次，结果不会变。请换个方式（读源码/写局部用例/回滚）。"
            if repeat_counts[key] >= 5:
                abort_reason = "repeated_action"
                res.failure_mode = "repeated_action"
                messages += [{"role": "assistant", "content": text[:600]},
                             {"role": "user", "content": observation}]
                break
            if read_streak >= 7:
                abort_reason = "stuck_reading"
                res.failure_mode = "stuck_reading"
                messages += [{"role": "assistant", "content": text[:600]},
                             {"role": "user", "content": observation + "\n[护栏] 连续 7 步只读不写，终止。"}]
                break

            # 同一批失败测试连续出现（即：这次改动没有改变任何失败项）-> 撤销最近一次写。
            # 用"失败测试集合"而不是整段输出哈希：断言的期望/实际值会随编辑变化，
            # 旧实现因此永远判不出"没有进展"，回滚分支在 64 条记录里一次都没进过。
            if name == "run_tests" and not out.ok and self.toolbox.enable_rollback:
                res.rollback_checks += 1
                ids = str(out.meta.get("failed_ids") or "")
                digest = out.meta.get("digest")
                same = bool(ids) and ids == last_fail_ids and writes_since_test > 0
                if not ids:  # 解析不到测试 id 时退回指纹比较
                    same = bool(digest) and digest == last_test_digest and writes_since_test > 0
                if DEBUG_GUARD:
                    trajectory.append(
                        f"  [guard] step={step} failed_ids={ids[:120]!r} prev={last_fail_ids[:120]!r} "
                        f"writes={writes_since_test} digest={digest} same={same} ckpt={self.toolbox.snap.latest()}")
                last_fail_ids, last_test_digest = ids, digest
                writes_since_test = 0
                if same:
                    cid = self.toolbox.snap.latest()
                    if cid:
                        rep = self.toolbox.snap.restore(cid)
                        res.rollback_used += 1
                        res.rollback_verified = res.rollback_verified or rep.verified
                        observation += (
                            f"\n[护栏] 失败测试集合与上次完全相同（{ids[:100]}），说明刚做的改动没有进展，"
                            f"已回滚到 {cid}（恢复 {rep.restored} 文件，哈希校验"
                            f"{'通过' if rep.verified else '失败'}）。换思路。"
                        )
                        trajectory.append(f"  回滚: {cid} verified={rep.verified} "
                                          f"restored={rep.restored} removed={rep.removed}")
                        last_fail_ids, last_test_digest, writes_since_test = "", None, 0

            if name == "rollback":
                # 只有真正执行的恢复才算一次回滚；被权限拒绝的调用（如 no_rollback 臂）不计。
                if out.ok:
                    res.rollback_used += 1
                    if out.meta.get("verified"):
                        res.rollback_verified = True

            # 优化模式：可见测试通过就收工，省一次模型调用。
            # 但必须用完整判分（含隐藏测试）确认；判分不过就继续，
            # 否则这条"降本手段"会直接吞掉本可成功的任务（实测导致 cache_state-counter_reset 变错）。
            if self.cost.auto_finish_on_pass and name == "run_tests" and out.ok:
                probe = judge_fn()
                trajectory.append(f"  提前结束判定: {probe[1][:200]}")
                if probe[0]:
                    judged = probe
                    break
                observation += "\n[提示] 可见测试通过，但未公开的隐藏测试仍未通过。请继续检查边界情况。"
                judged = None

            messages += [{"role": "assistant", "content": text[:1200]},
                         {"role": "user", "content": "观察结果:\n" + observation}]
            if self.cost.history_window and len(messages) > 3 + self.cost.history_window:
                # 被裁掉的部分压成一行摘要，避免模型"忘了读过什么"而反复重读
                dropped = messages[2 : len(messages) - self.cost.history_window]
                for m in dropped:
                    if m["role"] == "user" and m["content"].startswith("观察结果"):
                        early.append(m["content"].splitlines()[0][:100])
                    elif m["role"] == "assistant":
                        early.append(m["content"][:80])
                early = early[-10:]
                tail = messages[-self.cost.history_window:]
                progress = (f"[上下文裁剪] 已执行 {step} 步。早前动作摘要:\n" + "\n".join(early)
                            if early else f"[上下文裁剪] 已执行 {step} 步。")
                messages = messages[:2] + [{"role": "user", "content": progress}] + tail

        if judged is None:
            judged = judge_fn()
        res.success, res.judge_detail = judged
        res.calls = self.usage.calls
        res.prompt_tokens = self.usage.prompt_tokens
        res.completion_tokens = self.usage.completion_tokens
        res.cached_tokens = self.usage.cached_tokens
        if not res.success and not res.failure_mode:
            res.failure_mode = "wrong_fix" if not abort_reason else abort_reason

        # 失败 -> 反思 -> 写入结构化记忆
        if not res.success and self.memory is not None:
            version = getattr(self.memory, "version", "v1")
            lesson, u, note = self._reflect(task, trajectory, res.judge_detail, version=version)
            res.reflect_calls = u.calls
            res.reflect_prompt_tokens = u.prompt_tokens
            res.reflect_completion_tokens = u.completion_tokens
            if note:
                trajectory.append(f"  反思异常: {note}")
                res.error = note[:200]
            if lesson:
                lesson["family"] = task.get("family", "")
                lesson["source_task"] = task["id"]
                known = set(task.get("src_identifiers") or [])
                known |= {p.stem for p in (self.toolbox.root / "src").glob("*.py")}
                text = " ".join(str(lesson.get(k, "")) for k in (
                    "scenario", "symptom", "root_cause", "fix_pattern", "rule"))
                lesson["scope"] = sorted(i for i in known if i in text)
                if version in ("v2", "v3"):
                    # v2/v3：按 bug 类别归类，不要求函数锚点（锚点只做检索排序加分）
                    cat = normalize_category(lesson.get("bug_category"), task.get("family", ""))
                    if not cat:
                        self.memory.reject("no_category", lesson)
                        trajectory.append("  反思丢弃: 无法归入任何 bug 类别")
                    else:
                        lesson["bug_category"] = cat
                        lesson["scenario"] = lesson.get("scenario") or lesson.get("symptom", "")
                        lesson["error_type"] = cat
                        lesson["rule"] = lesson.get("rule") or lesson.get("fix_pattern", "")
                        lid, _ = self.memory.add(lesson)
                        if not lid:
                            trajectory.append("  反思丢弃: 记忆层判定为 prompt 复述")
                else:
                    # v1：没有具体锚点的教训无法验证是否可迁移，直接丢弃
                    if not lesson["scope"]:
                        self.memory.reject("no_anchor", lesson)
                        trajectory.append("  反思丢弃: 教训没有具体函数/文件锚点，不可迁移")
                    else:
                        lid, _ = self.memory.add(lesson)
                        if not lid:
                            trajectory.append("  反思丢弃: 记忆层判定为 prompt 复述")
        if self.memory is not None and injected:
            self.memory.feedback(injected, res.success)

        res.latency_s = round(time.time() - t0, 1)
        if trace_path:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.write_text("\n".join(trajectory))
        return res


def run_with_retry(agent: ReactAgent, task: dict, judge_fn, arm: str, trace_path: Path, max_retry: int = 1) -> EpisodeResult:
    """LLM 层瞬时故障时重跑一次；任务逻辑失败不重跑（保持成功率定义干净）。"""
    last = None
    for _ in range(max_retry + 1):
        try:
            r = agent.run(task, judge_fn, arm=arm, trace_path=trace_path)
        except Exception as e:  # 循环内部异常（非任务失败）
            r = EpisodeResult(task_id=task["id"], arm=arm, success=False, failure_mode="harness_error",
                              error=f"{type(e).__name__}: {e}")
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.write_text(traceback.format_exc())
        last = r
        if r.failure_mode not in ("llm_error", "harness_error"):
            return r
    return last
