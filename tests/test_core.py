"""核心不变量测试：协议解析、记忆检索、快照回滚、工具边界、失败指纹。

这些测试不依赖 LLM：跑 `python -m pytest tests -q` 即可。
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from agent.config import cost_mode  # noqa: E402
from agent.loop import extract_action, extract_json_any  # noqa: E402
from agent.memory import ReflectionMemory, is_usable, jaccard, tokenize  # noqa: E402
from agent.rollback import SnapshotManager  # noqa: E402
from agent.tools import Toolbox, failure_digest  # noqa: E402


# ---------- 协议解析 ----------
def test_extract_action_plain_json():
    text = '思考: 先跑测试\n{"action": "run_tests", "args": {}}'
    act = extract_action(text)
    assert act["action"] == "run_tests" and act["args"] == {}


def test_extract_action_with_nested_braces_in_string():
    text = '{"thought":"把 dict 写成 {}", "action":"edit_file", "args":{"path":"a.py","old":"x","new":"y"}}'
    act = extract_action(text)
    assert act["action"] == "edit_file"
    assert act["args"]["path"] == "a.py"


def test_extract_action_rejects_missing_action():
    assert extract_action('{"subgoals": ["a", "b"]}') is None


def test_extract_action_handles_fence_and_noise():
    text = "我先分析一下。\n```json\n{\"action\":\"read_file\",\"args\":{\"path\":\"src/a.py\"}}\n```\n完毕。"
    act = extract_action(text)
    assert act["action"] == "read_file" and act["args"]["path"] == "src/a.py"


def test_extract_json_any_without_action_key():
    assert extract_json_any('{"scenario":"x","root_cause":"y"}') == {"scenario": "x", "root_cause": "y"}


def test_extract_json_any_returns_none_on_prose():
    assert extract_json_any("模型先输出了一大段推理，没有 JSON") is None


# ---------- 记忆 ----------
def _mem(tmp_path: Path) -> ReflectionMemory:
    return ReflectionMemory(tmp_path / "mem.jsonl")


def test_is_usable_rejects_placeholder():
    assert not is_usable({"root_cause": "...", "rule": "..."})
    assert not is_usable({"root_cause": "短", "rule": "也短"})
    assert is_usable({"root_cause": "只修了可见测试覆盖的模块，漏掉隐藏测试的另一模块",
                      "rule": "多模块任务先读全部 src 文件再动手"})


def test_is_usable_rejects_prompt_boilerplate():
    """只复述系统提示、没有具体锚点的教训不得入库（实测会被注入 19 次，纯增上下文）。"""
    boiler = {"root_cause": "没有逐模块检查导致另一个模块的缺陷遗漏",
              "rule": "不得修改 tests；修复 src 所有缺陷并验证后调用 finish。"}
    assert not is_usable(boiler)
    concrete = {"root_cause": "parse_kv 在空值分支没有返回 None",
                "rule": "parse_kv 与 parse_range 的空值分支都要补 None 返回"}
    assert is_usable(concrete)


def test_memory_dedup_merges_similar_lesson(tmp_path):
    m = _mem(tmp_path)
    base = {"family": "f", "scenario": "多模块任务只修了一个文件", "error_type": "incomplete",
            "root_cause": "只看了可见测试覆盖的模块", "fix_pattern": "先列清单再逐个读",
            "rule": "多模块任务先读全部 src 文件再动手", "source_task": "t1"}
    lid1, created1 = m.add(base)
    same = dict(base, source_task="t2")
    lid2, created2 = m.add(same)
    assert created1 and not created2 and lid1 == lid2
    assert m.lessons[lid1].dedup_hits == 1


def test_memory_scope_filters_wrong_task(tmp_path):
    m = _mem(tmp_path)
    m.add({"family": "types", "scenario": "数值相加", "error_type": "type",
           "root_cause": "add_numbers 对字符串也直接相加", "fix_pattern": "先校验类型",
           "rule": "add_numbers 必须先做类型校验", "source_task": "t",
           "scope": ["add_numbers"]})
    task = {"prompt": "修复 parse_csv_line 的解析错误",
            "retrieval_hint": "parsing parse_csv_line", "src_identifiers": ["parse_csv_line", "main"]}
    got, _ = m.retrieve(task, k=2, max_chars=400)
    assert got == []


def test_memory_retrieve_hits_matching_scope(tmp_path):
    m = _mem(tmp_path)
    m.add({"family": "boundary", "scenario": "二分边界 off-by-one", "error_type": "boundary",
           "root_cause": "last_le 用了 < 而不是 <=", "fix_pattern": "把 < 改为 <=",
           "rule": "last_le 的右边界条件应为 <=", "source_task": "t",
           "scope": ["last_le"]})
    task = {"prompt": "修复 last_le 的边界错误",
            "retrieval_hint": "boundary last_le", "src_identifiers": ["last_le", "main"]}
    got, _ = m.retrieve(task, k=2, max_chars=400)
    assert len(got) == 1 and got[0].scope == ["last_le"]


def test_memory_feedback_persists_and_reloads(tmp_path):
    m = _mem(tmp_path)
    lid, _ = m.add({"family": "f", "scenario": "x", "error_type": "e",
                    "root_cause": "失败后没有先复现，直接盲改源码导致越改越乱", "fix_pattern": "先跑测试复现",
                    "rule": "失败后先复现最小用例再动手", "source_task": "t"})
    assert lid
    m.feedback([lid], success=False)
    m2 = ReflectionMemory(tmp_path / "mem.jsonl")
    assert m2.lessons[lid].fail_after == 1


def test_memory_injection_count_recorded(tmp_path):
    m = _mem(tmp_path)
    m.add({"family": "f", "scenario": "多模块只改一个文件", "error_type": "incomplete",
           "root_cause": "只读了第一个模块，漏掉隐藏测试覆盖的第二个模块", "fix_pattern": "先列清单",
           "rule": "多模块任务先读全部 src 文件再动手", "source_task": "t", "scope": ["main"]})
    task = {"id": "t2", "family": "f", "prompt": "多模块只改一个文件，漏掉隐藏测试覆盖的模块",
            "retrieval_hint": "src main 模块", "src_identifiers": ["main"]}
    got, text = m.retrieve(task, k=2, max_chars=400)
    assert text and m.injections["t2"] == len(got)


def test_memory_skips_cross_family_without_scope_hit(tmp_path):
    """跨任务族且没命中当前仓库函数名的教训不得注入（历史实验里这类注入导致 6 个任务变错）。"""
    m = _mem(tmp_path)
    m.add({"family": "cache_state", "scenario": "多模块只改一个文件", "error_type": "incomplete",
           "root_cause": "只读了第一个模块，漏掉隐藏测试覆盖的第二个模块", "fix_pattern": "先列清单",
           "rule": "多模块任务先读全部 src 文件再动手", "source_task": "t", "scope": ["parse_range"]})
    task = {"id": "t3", "family": "boundary", "prompt": "多模块只改一个文件，漏掉隐藏测试覆盖的模块",
            "retrieval_hint": "src main 模块", "src_identifiers": ["main", "last_le"]}
    got, text = m.retrieve(task, k=2, max_chars=400)
    assert got == [] and text == ""


def test_memory_quarantines_disproved_lesson(tmp_path):
    m = _mem(tmp_path)
    lid, _ = m.add({"family": "f", "scenario": "同一场景反复失败", "error_type": "wrong_fix",
                    "root_cause": "改完没有跑隐藏测试就结束", "fix_pattern": "先跑全量测试",
                    "rule": "每次改完都跑全量测试", "source_task": "t", "scope": ["main"]})
    assert lid
    m.feedback([lid], success=False)
    m.feedback([lid], success=False)
    task = {"id": "t4", "family": "f", "prompt": "同一场景反复失败",
            "retrieval_hint": "main", "src_identifiers": ["main"]}
    got, _ = m.retrieve(task, k=2, max_chars=400)
    assert got == []


# ---------- 回滚 ----------
def test_snapshot_restore_verifies_hash(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("v1")
    (ws / "sub").mkdir()
    (ws / "sub" / "b.txt").write_text("keep")
    sm = SnapshotManager(ws)
    cid = sm.snapshot("t")
    (ws / "a.txt").write_text("v2-broken")
    (ws / "new.txt").write_text("should disappear")
    rep = sm.restore(cid)
    assert rep.verified
    assert (ws / "a.txt").read_text() == "v1"
    assert not (ws / "new.txt").exists()
    assert rep.removed == 1


def test_snapshot_latest_is_most_recent(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("v1")
    sm = SnapshotManager(ws)
    c1 = sm.snapshot("one")
    (ws / "a.txt").write_text("v2")
    c2 = sm.snapshot("two")
    assert sm.latest() == c2 != c1


# ---------- 工具边界 ----------
def _toolbox(tmp_path: Path) -> Toolbox:
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "tests").mkdir()
    (ws / "src" / "m.py").write_text("def f():\n    return 1\n")
    (ws / "tests" / "test_m.py").write_text("from m import f\n\ndef test_f():\n    assert f() == 1\n")
    return Toolbox(ws, cost=cost_mode("baseline"))


def test_tools_block_path_traversal(tmp_path):
    tb = _toolbox(tmp_path)
    out = tb.call("read_file", {"path": "../../etc/passwd"})
    assert not out.ok and "越界" in out.content


def test_tools_block_test_writes(tmp_path):
    tb = _toolbox(tmp_path)
    out = tb.call("write_file", {"path": "tests/test_m.py", "content": "def test_x(): pass"})
    assert not out.ok and "只读" in out.content


def test_tools_return_errors_instead_of_raising(tmp_path):
    tb = _toolbox(tmp_path)
    out = tb.call("edit_file", {"path": "src/m.py", "old": "不存在的内容", "new": "x"})
    assert not out.ok and "未找到" in out.content


def test_read_file_truncates_output(tmp_path):
    tb = _toolbox(tmp_path)
    big = "x" * 5000
    (tb.root / "src" / "big.txt").write_text(big)
    out = tb.call("read_file", {"path": "src/big.txt"})
    assert "截断" in out.content


def test_tool_memo_skips_repeat_read(tmp_path):
    tb = _toolbox(tmp_path)
    tb.cost = cost_mode("optimized")
    tb.call("read_file", {"path": "src/m.py"})
    out = tb.call("read_file", {"path": "src/m.py"})
    assert "命中缓存" in out.content


def test_write_invalidates_memo(tmp_path):
    tb = _toolbox(tmp_path)
    tb.cost = cost_mode("optimized")
    tb.call("read_file", {"path": "src/m.py"})
    tb.call("edit_file", {"path": "src/m.py", "old": "return 1", "new": "return 2"})
    out = tb.call("read_file", {"path": "src/m.py"})
    assert "return 2" in out.content


def test_rollback_tools_disabled_when_flag_off(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("x")
    tb = Toolbox(ws, cost=cost_mode("baseline"), enable_rollback=False)
    out = tb.call("rollback", {})
    assert not out.ok


# ---------- 失败指纹 ----------
def test_failure_digest_ignores_timing():
    a = failure_digest("FAILED tests/test_x.py::test_a - assert 0 == 1\n1 failed in 0.05s")
    b = failure_digest("FAILED tests/test_x.py::test_a - assert 0 == 1\n1 failed in 1.23s")
    assert a == b


def test_failure_digest_distinguishes_different_failures():
    a = failure_digest("FAILED tests/test_x.py::test_a - assert 0 == 1")
    b = failure_digest("FAILED tests/test_x.py::test_b - assert 2 == 3")
    assert a != b


# ---------- 记忆 v2：bug 类别作用域 ----------
def test_infer_categories_from_observable_text():
    from agent.memory import infer_categories
    cats = infer_categories("修复 search.py 的 insert_position_desc；assert lower_bound([],5)==0")
    assert "boundary_compare" in cats
    cats2 = infer_categories("parse_csv_line 在空字段时抛 ValueError")
    assert "parsing_robustness" in cats2


def test_v2_injects_across_functions_same_category(tmp_path):
    """v2 的核心：类别相同即可迁移，函数名不同不再硬过滤。"""
    m = ReflectionMemory(tmp_path / "m.jsonl", version="v2")
    lid, _ = m.add({"bug_category": "boundary_compare", "symptom": "空数组时返回 -1",
                    "root_cause": "二分上界写成 len(arr)-1，越界时漏掉末尾位置",
                    "fix_pattern": "把初始上界改为 len(arr)", "source_task": "a",
                    "scope": ["lower_bound"]})
    assert lid
    task = {"id": "b", "prompt": "修复 insert_position_desc 的边界错误",
            "retrieval_hint": "insert_position_desc", "src_identifiers": ["insert_position_desc"],
            "observed_categories": ["boundary_compare"]}
    got, text = m.retrieve(task, k=2, max_chars=400)
    assert len(got) == 1 and got[0].id == lid and text


def test_v1_does_not_inject_across_functions(tmp_path):
    """对照：v1 的函数名硬过滤会把同类别但不同函数的教训挡掉。"""
    m = ReflectionMemory(tmp_path / "m.jsonl", version="v1")
    lid, _ = m.add({"family": "boundary", "scenario": "二分边界", "error_type": "boundary",
                    "root_cause": "二分上界写成 len(arr)-1，越界时漏掉末尾位置",
                    "fix_pattern": "把初始上界改为 len(arr)", "rule": "二分初始上界用 len(arr)",
                    "source_task": "a", "scope": ["lower_bound"]})
    assert lid
    task = {"id": "b", "family": "boundary", "prompt": "修复 insert_position_desc 的边界错误",
            "retrieval_hint": "insert_position_desc", "src_identifiers": ["insert_position_desc"]}
    got, _ = m.retrieve(task, k=2, max_chars=400)
    assert got == []


def test_v2_quarantine_still_applies(tmp_path):
    m = ReflectionMemory(tmp_path / "m.jsonl", version="v2")
    lid, _ = m.add({"bug_category": "parsing_robustness", "symptom": "空字段抛异常",
                    "root_cause": "parse_kv 对空值没有返回 None", "fix_pattern": "空值分支返回 None",
                    "source_task": "t"})
    assert lid
    m.feedback([lid], success=False)
    m.feedback([lid], success=False)
    task = {"id": "x", "prompt": "parse_kv 空值失败", "retrieval_hint": "parse_kv",
            "src_identifiers": ["parse_kv"], "observed_categories": ["parsing_robustness"]}
    got, _ = m.retrieve(task, k=2, max_chars=400)
    assert got == []


def test_parse_arm_memory_versions():
    from bench.runner import parse_arm
    assert parse_arm("no_memory__baseline") == (None, "baseline")
    assert parse_arm("mem_v1__baseline") == ("v1", "baseline")
    assert parse_arm("mem_v2__baseline") == ("v2", "baseline")
    assert parse_arm("mem_v3__baseline") == ("v3", "baseline")


def test_v3_injects_only_top1_and_caps_chars(tmp_path):
    """v3：只注入 top-1，且渲染后单条不超过 200 字、总量不超过 220 字。"""
    m = ReflectionMemory(tmp_path / "m.jsonl", version="v3")
    ids = []
    for i in range(2):
        lid, _ = m.add({
            "bug_category": "paging_index", "symptom": "last_page 返回空列表",
            "root_cause": "last_page 用 len(items) // per_page 作下标，整除时越界",
            "fix_pattern": f"last_page(items, per_page) 在 len(items) 整除 per_page 时应返回空列表（v{i}）",
            "source_task": f"t{i}",
        })
        ids.append(lid)
    task = {"id": "x", "prompt": "修复分页 last_page 的越界", "retrieval_hint": "last_page",
            "src_identifiers": ["last_page"], "observed_categories": ["paging_index"]}
    got, text = m.retrieve(task, k=3, max_chars=900)
    assert len(got) == 1                  # top-1，不受传入 k 影响
    assert len(got[0].fix_pattern) <= 200
    body = text.split("\n", 1)[1]
    assert len(body) <= 220


def test_v3_gate_rejects_vague_lesson(tmp_path):
    """(a) 缺具体符号 -> 不注入。"""
    m = ReflectionMemory(tmp_path / "m.jsonl", version="v3")
    lid, _ = m.add({"bug_category": "boundary_compare", "symptom": "边界测试失败",
                    "root_cause": "判断条件写反了，导致结果不正确",
                    "fix_pattern": "下次先确认比较方向再继续处理", "source_task": "t"})
    assert lid
    task = {"id": "x", "prompt": "边界比较失败", "retrieval_hint": "边界",
            "observed_categories": ["boundary_compare"]}
    got, text = m.retrieve(task, k=1, max_chars=900)
    assert got == [] and text == ""


def test_v3_gate_rejects_without_verifiable_check(tmp_path):
    """(b) 有符号但没有可验证判据 -> 不注入。"""
    m = ReflectionMemory(tmp_path / "m.jsonl", version="v3")
    lid, _ = m.add({"bug_category": "cache_state", "symptom": "缓存没有复位",
                    "root_cause": "reset 只清空了 entries，没有把 counter 归零",
                    "fix_pattern": "在 reset 里一并重置 counter 和 entries", "source_task": "t"})
    assert lid
    task = {"id": "x", "prompt": "修复 cache 的 counter_reset", "retrieval_hint": "counter_reset",
            "observed_categories": ["cache_state"]}
    got, _ = m.retrieve(task, k=1, max_chars=900)
    assert got == []


def test_v3_gate_accepts_specific_and_verifiable(tmp_path):
    m = ReflectionMemory(tmp_path / "m.jsonl", version="v3")
    lid, _ = m.add({"bug_category": "parsing_robustness", "symptom": "空字段导致 ValueError",
                    "root_cause": "parse_kv 对空字符串直接 float('') 抛 ValueError",
                    "fix_pattern": "parse_kv('') 应返回 None；空值分支先判断 key/value 是否为空",
                    "source_task": "t"})
    assert lid
    task = {"id": "x", "prompt": "parse_kv 空值失败", "retrieval_hint": "parse_kv",
            "observed_categories": ["parsing_robustness"]}
    got, text = m.retrieve(task, k=1, max_chars=900)
    assert len(got) == 1 and got[0].id == lid and text


# ---------- 任务集自检 ----------
def test_task_set_size_and_reference_solution():
    from bench.judge import judge_with_reference
    from bench.tasks import load_tasks
    tasks = load_tasks()
    assert len(tasks) >= 250, f"任务集只有 {len(tasks)} 个"
    ok, detail = judge_with_reference(tasks[0])
    assert ok, detail


def test_task_categories_balanced():
    from bench.tasks import load_tasks
    import collections
    tasks = load_tasks()
    counts = collections.Counter(t["bug_category"] for t in tasks)
    assert len(counts) == 8
    assert min(counts.values()) >= 15, counts
