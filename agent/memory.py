"""结构化反思记忆：场景 / 错误 / 根因 / 下次怎么做，可检索、可去重、可统计命中效果。

v1 用函数名做作用域硬过滤；实验证明这会把跨任务泛化杀掉（64 题里注入 0 次）。
v2 改为 bug 类别作用域：检索分 = 类别匹配 + 症状相似度，函数名只做排序加分。
v3 在 v2 打分上加"具体性闸门"并只注入 top-1：
  教训必须同时有点名符号/条件、可验证判据、类别匹配，缺一不注入；
  单条渲染硬截断 200 字，单题注入预算 220 字，用来压住 token 成本。

存储为 append-only JSONL 事件流：
  {"type":"add", "lesson":{...}}
  {"type":"feedback", "id":"...", "outcome":"success|fail"}
加载时重建状态，因此中途崩溃不会损坏记忆。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

STOPWORDS = set(
    """a an the is are was be been to of in on at for with and or not no it this that these those
    you your i we they he she do does did done can could should would will if then than as by from
    python code test tests file files function fix bug source workspace agent json call tool step
    """ .split()
)

# ---------- bug 类别（v2 的检索作用域） ----------
CATEGORIES = [
    "boundary_compare",
    "paging_index",
    "reduce_init",
    "mutable_default",
    "cache_state",
    "parsing_robustness",
    "recursion_base",
    "type_conversion",
]

CATEGORY_ZH = {
    "boundary_compare": "边界比较/off-by-one",
    "paging_index": "分页/切片索引",
    "reduce_init": "归约初值/比较器",
    "mutable_default": "可变默认参数/共享状态",
    "cache_state": "缓存/状态失效",
    "parsing_robustness": "解析容错",
    "recursion_base": "递归终止/基例",
    "type_conversion": "类型转换/空值",
}

FAMILY_TO_CATEGORY = {
    "boundary": "boundary_compare",
    "paging": "paging_index",
    "reduce_init": "reduce_init",
    "mutable_default": "mutable_default",
    "cache_state": "cache_state",
    "parsing": "parsing_robustness",
    "recursion": "recursion_base",
    "types": "type_conversion",
}

# 只用于"从可观察文本推断类别"的词典：源码函数名、可见测试名、失败信息里的词。
# 不含任何 ground-truth 文件；Agent 读了 tests/src 就能看到同样的词。
CATEGORY_KEYWORDS = {
    "boundary_compare": [
        "lower_bound", "upper_bound", "bisect", "insert_position", "first_nonnegative",
        "peak_index", "rotated", "search_rotated", "off_by_one", "off-by-one",
        "mid =", "lo, hi", "边界", "二分", "len(arr) - 1", "len(arr)-1",
    ],
    "paging_index": [
        "paging", "page", "last_page", "paginate", "slice", "chunk", "offset",
        "limit", "per_page", "分页", "切片",
    ],
    "reduce_init": [
        "reduce", "fold", "min_or_none", "max_or_none", "argmax", "argmin",
        "initial", "initializer", "归约", "初值", "比较器",
    ],
    "mutable_default": [
        "mutable", "default", "stack", "append", "shared", "collect", "可变默认",
        "默认参数", "共享",
    ],
    "cache_state": [
        "cache", "memo", "reset", "state", "counter_reset", "batch_flush",
        "缓存", "状态",
    ],
    "parsing_robustness": [
        "parse", "csv", "parse_kv", "parse_range", "parse_float", "split",
        "strip", "解析", "容错",
    ],
    "recursion_base": [
        "recursion", "recursive", "tree", "count_nodes", "tree_height",
        "base case", "递归", "基例", "终止",
    ],
    "type_conversion": [
        "format", "normalize", "to_int", "to_float", "format_price", "type(",
        "isinstance", "str", "类型", "转换", "空值",
    ],
}


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{1,}|[\u4e00-\u9fff]{1,4}", (text or "").lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def normalize_category(value: str | None, family: str = "") -> str:
    """把模型输出/旧字段归一化到 CATEGORIES；未知则按 family 推断。"""
    v = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if v in CATEGORIES:
        return v
    for cat, zh in CATEGORY_ZH.items():
        if v == zh:
            return cat
    for token in str(family or "").split("+"):
        if token in FAMILY_TO_CATEGORY:
            return FAMILY_TO_CATEGORY[token]
    return ""


def infer_categories(text: str) -> set[str]:
    """从 Agent 可观察文本（prompt / 可见测试名 / 源码标识符 / 失败输出）推断 bug 类别。"""
    low = (text or "").lower()
    hits = set()
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w.lower() in low for w in words):
            hits.add(cat)
    for cat in CATEGORIES:
        if cat in low or CATEGORY_ZH[cat] in low:
            hits.add(cat)
    return hits


_PLACEHOLDERS = {"...", "…", "待定", "todo", "unknown", "n/a"}

# 这些词只是复述系统提示，不构成"下次怎么做"的可执行信息
_BOILERPLATE_PHRASES = ("不得修改 tests", "不要修改测试", "调用 finish", "修复 src", "通读源码", "仔细检查")
_BOILERPLATE_TOKENS = {"tests", "test", "src", "finish", "pytest", "run_tests", "summary", "workspace", "json"}


def is_generic(lesson: dict) -> bool:
    """规则只是复述 prompt（"改测试、修 src、finish"）且没有任何具体锚点 -> 无迁移价值。"""
    rule = (lesson.get("rule") or lesson.get("fix_pattern") or "").strip()
    phrase_hits = sum(1 for p in _BOILERPLATE_PHRASES if p in rule)
    anchors = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", rule)) - _BOILERPLATE_TOKENS
    anchors |= set(re.findall(r"[`「【]([a-zA-Z_][a-zA-Z0-9_]{2,})", rule))
    return phrase_hits >= 1 and not anchors


def is_usable(lesson: dict) -> bool:
    """拒绝空话/占位符教训：根因和做法必须是有内容的句子，且不是纯 prompt 复述。"""
    root = (lesson.get("root_cause") or "").strip()
    fix = (lesson.get("fix_pattern") or "").strip()
    rule = (lesson.get("rule") or "").strip()
    action = fix if len(fix) >= 8 else rule
    if len(root) < 10 or len(action) < 8:
        return False
    for text in (root, action):
        if text.lower() in _PLACEHOLDERS:
            return False
        if set(text) <= set(".…-— "):
            return False
    if is_generic(lesson):
        return False
    return True


# ---------- v3 具体性闸门 ----------
V3_ENTRY_CHARS = 200   # 每条教训渲染后的硬上限
V3_MAX_CHARS = 220     # 单题注入文本总预算

_GATE_GENERIC = STOPWORDS | _BOILERPLATE_TOKENS | {
    "the", "and", "when", "then", "should", "would", "could", "return", "returns",
    "value", "result", "input", "output", "case", "condition", "specific", "same",
    "different", "function", "parameter", "argument", "example", "expected", "actual",
    "line", "code", "python", "list", "dict", "str", "int", "float", "bool", "always",
    "never", "only", "avoid", "check", "consider", "ensure", "handle", "correct",
}
_GATE_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
_GATE_MINI_VAR = re.compile(r"\b[A-Za-z]\s*(?:<=|>=|==|!=|<|>|\+|-|\*|/|%)")
_GATE_CONDITION = (
    "空列表", "空字符串", "空输入", "空值", "负数", "零", "越界", "边界",
    "off-by-one", "off_by_one", "none", "null", "[]", '""', "''", "last_page",
    "first_page", "最后一个", "第一个", "缺失", "typeerror", "indexerror",
)
_GATE_VERIFY = re.compile(
    r"(?:应(?:该)?(?:返回|等于|输出|为)|期望|预期|断言|assert|returns?\b|"
    r"should return|expected|equals|==|>=|<=|!=|→|->)", re.I,
)


def has_specific_symbol(text: str) -> bool:
    """(a) 点名具体符号/函数/参数/条件。"""
    low = (text or "").lower()
    if any(c in low for c in _GATE_CONDITION):
        return True
    if _GATE_MINI_VAR.search(text or ""):
        return True
    for tok in _GATE_IDENT.findall(text or ""):
        if tok.lower() in _GATE_GENERIC:
            continue
        if len(tok) >= 3:
            return True
    return False


def has_verifiable_check(text: str) -> bool:
    """(b) 给出可验证判据：出现"应返回/期望/assert/=="等判据，且后面带具体值。"""
    for m in _GATE_VERIFY.finditer(text or ""):
        tail = text[m.end(): m.end() + 40]
        if re.search(r"\d", tail):
            return True
        if re.search(r"\b(none|null|true|false|list|dict|str|int|float|bool)\b", tail, re.I):
            return True
        if any(c in tail for c in ("[]", '""', "''", "空")):
            return True
        for tok in _GATE_IDENT.findall(tail):
            if tok.lower() not in _GATE_GENERIC and len(tok) >= 2:
                return True
    return False


@dataclass
class Lesson:
    id: str
    # v2 主字段
    bug_category: str = ""
    symptom: str = ""
    root_cause: str = ""
    fix_pattern: str = ""
    language_constraints: str = ""
    # 兼容 v1 / 展示
    family: str = ""
    scenario: str = ""
    error_type: str = ""
    rule: str = ""
    source_task: str = ""
    scope: list[str] = field(default_factory=list)  # 函数/标识符：v2 只做排序加分
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    hits: int = 0
    success_after: int = 0
    fail_after: int = 0
    dedup_hits: int = 0

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def effectiveness(self) -> str:
        if self.success_after + self.fail_after == 0:
            return "untested"
        return f"{self.success_after}/{self.success_after + self.fail_after}"

    @property
    def category(self) -> str:
        return self.bug_category or normalize_category("", self.family)

    def symptom_text(self) -> str:
        return " ".join(x for x in (self.symptom, self.scenario, self.error_type) if x)


class ReflectionMemory:
    def __init__(self, path: str | Path, version: str = "v1"):
        assert version in ("v1", "v2", "v3"), version
        self.path = Path(path)
        self.version = version
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lessons: dict[str, Lesson] = {}
        self.injections: dict[str, int] = {}
        self.rejects: dict[str, int] = {}
        self.gate_stats: dict[str, int] = {}
        self.last_render_chars = 0
        if self.path.exists():
            self._rebuild()

    # ---------- 持久化 ----------
    def _append(self, record: dict) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _rebuild(self) -> None:
        for line in self.path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "add":
                d = rec["lesson"]
                self.lessons[d["id"]] = Lesson(**{k: v for k, v in d.items() if k in Lesson.__dataclass_fields__})
            elif rec.get("type") == "feedback":
                lid = rec.get("id")
                if lid in self.lessons:
                    if rec.get("outcome") == "success":
                        self.lessons[lid].success_after += 1
                    else:
                        self.lessons[lid].fail_after += 1

    def state(self) -> dict:
        return {
            "path": str(self.path),
            "version": self.version,
            "n_lessons": len(self.lessons),
            "categories": sorted({l.category for l in self.lessons.values() if l.category}),
            "tested": sum(1 for l in self.lessons.values() if l.success_after + l.fail_after),
            "rejects": dict(self.rejects),
            "gate": dict(self.gate_stats),
        }

    def reject(self, reason: str, lesson: dict | None = None) -> None:
        """记录被拒收的教训（可观测性：为什么记忆没变多）。"""
        self.rejects[reason] = self.rejects.get(reason, 0) + 1
        rec = {"type": "reject", "reason": reason}
        if lesson:
            rec["root_cause"] = (lesson.get("root_cause") or "")[:200]
            rec["fix_pattern"] = (lesson.get("fix_pattern") or "")[:200]
        self._append(rec)

    # ---------- 写入 ----------
    def add(self, lesson: dict, dedup_threshold: float = 0.82) -> tuple[str, bool]:
        """返回 (lesson_id, 是否新建)。同类且根因相似则合并，不重复堆文本。"""
        if not is_usable(lesson):
            self.reject("boilerplate", lesson)
            return "", False
        family = lesson.get("family", "")
        category = normalize_category(lesson.get("bug_category"), family)
        group_key = category if self.version in ("v2", "v3") else family
        for existing in self.lessons.values():
            existing_key = existing.category if self.version in ("v2", "v3") else existing.family
            if existing_key != group_key:
                continue
            sim = jaccard(
                tokenize(existing.root_cause + " " + existing.rule),
                tokenize(lesson.get("root_cause", "") + " " + (lesson.get("rule") or lesson.get("fix_pattern", ""))),
            )
            if sim >= dedup_threshold:
                existing.dedup_hits += 1
                # 保留更具体的修复描述
                if len(lesson.get("fix_pattern", "")) > len(existing.fix_pattern):
                    existing.fix_pattern = lesson["fix_pattern"]
                self._append({"type": "add", "lesson": existing.as_dict(), "merged": True})
                return existing.id, False
        lid = lesson.get("id") or f"L{int(time.time() * 1000)}"
        obj = Lesson(
            id=lid,
            bug_category=category,
            symptom=(lesson.get("symptom") or lesson.get("scenario") or "")[:300],
            root_cause=lesson.get("root_cause", "")[:400],
            fix_pattern=(lesson.get("fix_pattern") or lesson.get("rule") or "")[:400],
            language_constraints=(lesson.get("language_constraints") or "")[:120],
            family=family,
            scenario=(lesson.get("scenario") or lesson.get("symptom") or "")[:300],
            error_type=(lesson.get("error_type") or category)[:80],
            rule=(lesson.get("rule") or lesson.get("fix_pattern") or "")[:400],
            source_task=lesson.get("source_task", ""),
            scope=list(lesson.get("scope") or [])[:10],
        )
        self.lessons[lid] = obj
        self._append({"type": "add", "lesson": obj.as_dict()})
        return lid, True

    def feedback(self, ids: list[str], success: bool) -> None:
        for lid in ids:
            if lid in self.lessons:
                outcome = "success" if success else "fail"
                self._append({"type": "feedback", "id": lid, "outcome": outcome})
                if success:
                    self.lessons[lid].success_after += 1
                else:
                    self.lessons[lid].fail_after += 1

    # ---------- 检索 ----------
    def retrieve(self, task: dict, k: int = 3, max_chars: int = 900) -> tuple[list[Lesson], str]:
        """按版本分派检索。task 只能带 Agent 可观察信息，不含 ground-truth。"""
        if self.version == "v3":
            return self._retrieve_v3(task, k, max_chars)
        if self.version == "v2":
            return self._retrieve_v2(task, k, max_chars)
        return self._retrieve_v1(task, k, max_chars)

    def _retrieve_v1(self, task: dict, k: int, max_chars: int) -> tuple[list[Lesson], str]:
        """v1：函数名硬过滤 + 同族限制。"""
        query = " ".join([task.get("prompt", ""), task.get("retrieval_hint", "")])
        qt = tokenize(query)
        current_ids = set(task.get("src_identifiers") or [])
        family = task.get("family", "")
        scored = []
        for l in self.lessons.values():
            if l.fail_after >= 2 and l.success_after == 0:
                continue
            if l.scope and current_ids and not (set(l.scope) & current_ids):
                continue
            scope_hit = bool(l.scope) and bool(current_ids) and bool(set(l.scope) & current_ids)
            if l.family != family and not scope_hit:
                continue
            lt = tokenize(l.scenario + " " + l.root_cause + " " + l.rule)
            score = 2.5 * jaccard(qt, lt)
            if scope_hit:
                score += 0.6 * (len(set(l.scope) & current_ids) / len(set(l.scope) | current_ids))
            if l.success_after + l.fail_after > 0 and l.fail_after > l.success_after:
                score -= 0.4
            if score > 0.22:
                scored.append((score, l))
        scored.sort(key=lambda x: (-x[0], x[1].created_at))
        chosen = [l for _, l in scored[:k]]
        for l in chosen:
            l.hits += 1
        self.injections[task.get("id", "")] = len(chosen)
        return chosen, self._render(task, chosen, max_chars)

    def _retrieve_v2(self, task: dict, k: int, max_chars: int) -> tuple[list[Lesson], str]:
        """v2：类别匹配 + 症状相似度；函数名只加分，不做任何硬过滤。

        隔离规则保留：连续失败 >=2 且从未成功过的教训不再注入。
        """
        query = " ".join([
            task.get("prompt", ""),
            task.get("retrieval_hint", ""),
            task.get("visible_failure", ""),
        ])
        qt = tokenize(query)
        current_ids = set(task.get("src_identifiers") or [])
        observed = set(task.get("observed_categories") or []) | infer_categories(query)
        scored = []
        for l in self.lessons.values():
            if l.fail_after >= 2 and l.success_after == 0:
                continue
            cat = l.category
            cat_hit = bool(cat) and cat in observed
            lt = tokenize(l.symptom_text() + " " + l.root_cause)
            symptom_sim = jaccard(qt, lt)
            anchor = 0.0
            if l.scope and current_ids:
                anchor = len(set(l.scope) & current_ids) / len(set(l.scope) | current_ids)
            score = 3.0 * float(cat_hit) + 2.0 * symptom_sim + 0.4 * anchor
            if l.success_after + l.fail_after > 0 and l.fail_after > l.success_after:
                score -= 0.3
            if score >= 0.5:
                scored.append((score, cat_hit, l))
        scored.sort(key=lambda x: (-x[0], -int(x[1]), x[2].created_at))
        chosen = [l for _, _, l in scored[:k]]
        for l in chosen:
            l.hits += 1
        self.injections[task.get("id", "")] = len(chosen)
        return chosen, self._render(task, chosen, max_chars)

    def _retrieve_v3(self, task: dict, k: int, max_chars: int) -> tuple[list[Lesson], str]:
        """v3：v2 打分 + 具体性闸门 + 只注入 top-1 + 每条 200 字硬截断。

        闸门要求同时满足：
          (a) 点名具体符号/函数/参数/条件；
          (b) 给出可验证判据（如"输入 [] 应返回 []"）；
          (c) bug_category 与当前任务的可观察类别匹配。
        任一不满足就换下一条候选；全都不满足则不注入。
        """
        k = 1
        max_chars = min(max_chars, V3_MAX_CHARS)
        query = " ".join([
            task.get("prompt", ""),
            task.get("retrieval_hint", ""),
            task.get("visible_failure", ""),
        ])
        qt = tokenize(query)
        current_ids = set(task.get("src_identifiers") or [])
        observed = set(task.get("observed_categories") or []) | infer_categories(query)
        scored = []
        for l in self.lessons.values():
            if l.fail_after >= 2 and l.success_after == 0:
                continue
            cat = l.category
            cat_hit = bool(cat) and cat in observed
            lt = tokenize(l.symptom_text() + " " + l.root_cause)
            score = 3.0 * float(cat_hit) + 2.0 * jaccard(qt, lt)
            if l.scope and current_ids:
                score += 0.4 * len(set(l.scope) & current_ids) / len(set(l.scope) | current_ids)
            if l.success_after + l.fail_after > 0 and l.fail_after > l.success_after:
                score -= 0.3
            if score >= 0.5:
                scored.append((score, cat_hit, l))
        scored.sort(key=lambda x: (-x[0], -int(x[1]), x[2].created_at))

        gate = {"no_category": 0, "no_symbol": 0, "no_check": 0}
        chosen: list[Lesson] = []
        for _, cat_hit, l in scored:
            if not cat_hit:
                gate["no_category"] += 1
                continue
            action = l.fix_pattern or l.rule
            if not has_specific_symbol(l.root_cause + " " + action):
                gate["no_symbol"] += 1
                continue
            if not has_verifiable_check(action + " " + l.symptom):
                gate["no_check"] += 1
                continue
            chosen = [l]
            break
        for reason, count in gate.items():
            if count:
                self.gate_stats[reason] = self.gate_stats.get(reason, 0) + count
        for l in chosen:
            l.hits += 1
        self.injections[task.get("id", "")] = len(chosen)
        return chosen, self._render(task, chosen, max_chars)

    def _render(self, task: dict, chosen: list[Lesson], max_chars: int) -> str:
        block = []
        used = 0
        for l in chosen:
            if self.version == "v3":
                # 先放可执行判据（fix_pattern 里含可验证条件），再补根因；整条硬截断 200 字。
                action = (l.fix_pattern or l.rule).strip()
                entry = f"- [{l.category}] {action}"
                root = (l.root_cause or "").strip()
                if root and len(entry) < V3_ENTRY_CHARS - 30:
                    entry += f"（根因: {root[:60]}）"
                entry = entry[:V3_ENTRY_CHARS]
            elif self.version == "v2":
                entry = (
                    f"- 类别: {l.category} | 症状: {(l.symptom or l.scenario)[:120]}\n"
                    f"  根因: {l.root_cause}\n  下次: {l.fix_pattern or l.rule}"
                )
                if l.language_constraints:
                    entry += f"\n  约束: {l.language_constraints}"
            else:
                entry = (
                    f"- 场景: {l.scenario}\n  错误: {l.error_type} | 根因: {l.root_cause}\n"
                    f"  下次: {l.fix_pattern or l.rule}"
                )
            if self.version != "v3":
                entry = entry[: max(80, max_chars // max(1, len(chosen)))]
            if used + len(entry) > max_chars:
                break
            block.append(entry)
            used += len(entry)
        text = ("历史教训（来自同类失败，仅供参考，需结合当前代码验证）:\n" + "\n".join(block)) if block else ""
        self.last_render_chars = len(text) - len("历史教训（来自同类失败，仅供参考，需结合当前代码验证）:\n") if block else 0
        return text

    def dump(self) -> list[dict]:
        return [l.as_dict() for l in self.lessons.values()]
