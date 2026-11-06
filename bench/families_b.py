"""任务族 B（F5-F8）。"""
from __future__ import annotations

from .families_a import V

F_STATE = {
    "name": "cache_state",
    "bug_class": "状态/缓存失效错误",
    "variants": [
        V("counter_reset", "state", '''
class Counter:
    def __init__(self):
        self.total = 0

    def add(self, x=1):
        self.total += x
        return self.total

    def reset(self):
        self.total = 0
        return self
''', ("    def reset(self):\n        self.total = 0\n        return self", "    def reset(self):\n        return self"),
          '''
from state import Counter

def test_counter_add():
    c = Counter()
    assert c.add(2) == 2
''',
          '''
from state import Counter

def test_reset_clears():
    c = Counter()
    c.add(5)
    c.reset()
    assert c.add(1) == 1

def test_reset_returns_self():
    c = Counter()
    assert c.reset() is c
''', "reset 没有清零累计值"),

        V("lru_get", "state", '''
class LRUCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.data = {}

    def get(self, key):
        if key not in self.data:
            return None
        value = self.data.pop(key)
        self.data[key] = value
        return value

    def put(self, key, value):
        if key in self.data:
            self.data.pop(key)
        elif len(self.data) >= self.capacity:
            self.data.pop(next(iter(self.data)))
        self.data[key] = value
''', ("        value = self.data.pop(key)\n        self.data[key] = value\n        return value", "        return self.data[key]"),
          '''
from state import LRUCache

def test_lru_put_get():
    c = LRUCache(2)
    c.put("a", 1)
    assert c.get("a") == 1
''',
          '''
from state import LRUCache

def test_lru_evicts_least_recently_used():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1
    c.put("c", 3)
    assert c.get("a") == 1
    assert c.get("b") is None

def test_lru_missing():
    assert LRUCache(2).get("x") is None
''', "get 没有刷新最近使用顺序，淘汰了刚访问的键"),

        V("config_cache", "state", '''
class Config:
    def __init__(self):
        self._cache = {}
        self._values = {}

    def set(self, k, v):
        self._values[k] = v
        self._cache.pop(k, None)

    def get(self, k, default=None):
        if k not in self._cache:
            self._cache[k] = self._values.get(k, default)
        return self._cache[k]
''', ("        self._values[k] = v\n        self._cache.pop(k, None)", "        self._values[k] = v"),
          '''
from state import Config

def test_config_get_default():
    c = Config()
    assert c.get("x", 0) == 0
''',
          '''
from state import Config

def test_set_invalidates_cache():
    c = Config()
    assert c.get("a") is None
    c.set("a", 1)
    assert c.get("a") == 1
    c.set("a", 2)
    assert c.get("a") == 2

def test_default_not_sticky():
    c = Config()
    assert c.get("a", 5) == 5
    c.set("a", 7)
    assert c.get("a") == 7
''', "set 更新后没有失效缓存，读到旧值"),

        V("ttl_cache", "state", '''
import time


class TTLCache:
    def __init__(self, ttl):
        self.ttl = ttl
        self._data = {}

    def set(self, k, v):
        self._data[k] = (v, time.time())

    def get(self, k):
        if k not in self._data:
            return None
        v, ts = self._data[k]
        if time.time() - ts > self.ttl:
            del self._data[k]
            return None
        return v
''', ("        if time.time() - ts > self.ttl:\n            del self._data[k]", "        if False:\n            del self._data[k]"),
          '''
from state import TTLCache

def test_ttl_immediate():
    c = TTLCache(10)
    c.set("a", 1)
    assert c.get("a") == 1
''',
          '''
import time
from state import TTLCache

def test_ttl_expires():
    c = TTLCache(0.05)
    c.set("a", 1)
    time.sleep(0.12)
    assert c.get("a") is None

def test_ttl_missing():
    assert TTLCache(1).get("z") is None
''', "TTL 过期判断被禁用，过期键仍然返回值"),

        V("shared_cache", "state", '''
class Memo:
    def __init__(self):
        self.cache = {}

    def compute(self, x):
        if x not in self.cache:
            self.cache[x] = x * 3
        return self.cache[x]
''', ("    def __init__(self):\n        self.cache = {}", "    cache = {}\n\n    def __init__(self):\n        pass"),
          '''
from state import Memo

def test_memo_basic():
    assert Memo().compute(2) == 6
''',
          '''
from state import Memo

def test_instances_isolated():
    a, b = Memo(), Memo()
    a.compute(2)
    assert b.compute(4) == 12
    assert a.compute(2) == 6

def test_cache_len():
    m = Memo()
    m.compute(1)
    assert len(m.cache) == 1

def test_cache_not_shared_across_instances():
    a = Memo()
    a.compute(1)
    a.compute(2)
    b = Memo()
    assert len(b.cache) == 0
''', "缓存挂在类属性上，所有实例共享"),

        V("square_cache_key", "state", '''
class SquareCache:
    def __init__(self):
        self.cache = {}

    def get(self, x):
        key = x
        if key not in self.cache:
            self.cache[key] = x * x
        return self.cache[key]
''', ("        key = x", "        key = type(x).__name__"),
          '''
from state import SquareCache

def test_square_single():
    assert SquareCache().get(3) == 9
''',
          '''
from state import SquareCache

def test_square_distinct_values():
    c = SquareCache()
    assert c.get(2) == 4
    assert c.get(3) == 9
    assert c.get(2) == 4

def test_cache_size():
    c = SquareCache()
    c.get(2)
    c.get(3)
    assert len(c.cache) == 2
''', "缓存键只用类型名，所有同类型输入互相覆盖"),

        V("batch_flush", "state", '''
class BatchStats:
    def __init__(self):
        self.items = []

    def add(self, x):
        self.items.append(x)

    def flush(self):
        vals = list(self.items)
        self.items = []
        return sum(vals) / len(vals) if vals else None
''', ("        vals = list(self.items)\n        self.items = []", "        vals = list(self.items)"),
          '''
from state import BatchStats

def test_flush_mean():
    b = BatchStats()
    b.add(2)
    b.add(4)
    assert b.flush() == 3.0
''',
          '''
from state import BatchStats

def test_flush_clears():
    b = BatchStats()
    b.add(1)
    b.add(3)
    b.flush()
    assert b.flush() is None

def test_flush_then_add():
    b = BatchStats()
    b.add(2)
    b.flush()
    b.add(6)
    assert b.flush() == 6.0
''', "flush 后未清空缓冲，下次统计重复计入"),

        V("token_bucket", "state", '''
class TokenBucket:
    def __init__(self, capacity):
        self.capacity = capacity
        self.tokens = capacity

    def take(self, n=1):
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def refill(self, n):
        self.tokens = min(self.capacity, self.tokens + n)
''', ("self.tokens = min(self.capacity, self.tokens + n)", "self.tokens = self.tokens + n"),
          '''
from state import TokenBucket

def test_bucket_take():
    b = TokenBucket(3)
    assert b.take(2) is True
''',
          '''
from state import TokenBucket

def test_bucket_refill_capped():
    b = TokenBucket(3)
    assert b.take(3) is True
    b.refill(10)
    assert b.tokens == 3

def test_bucket_exhausted():
    b = TokenBucket(2)
    b.take(2)
    assert b.take(1) is False
''', "补充令牌没有受容量上限约束"),
    ],
}

F_PARSING = {
    "name": "parsing",
    "bug_class": "解析边界情况",
    "variants": [
        V("parse_csv_line", "parsing", '''
def parse_csv_line(line):
    parts = []
    cur = ""
    in_quotes = False
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "," and not in_quotes:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts
''', ("    parts = []\n    cur = \"\"\n    in_quotes = False\n    for ch in line:\n        if ch == '\"':\n            in_quotes = not in_quotes\n        elif ch == \",\" and not in_quotes:\n            parts.append(cur)\n            cur = \"\"\n        else:\n            cur += ch\n    parts.append(cur)\n    return parts", "    return line.split(\",\")"),
          '''
from parsing import parse_csv_line

def test_csv_simple():
    assert parse_csv_line("a,b,c") == ["a", "b", "c"]
''',
          '''
from parsing import parse_csv_line

def test_csv_quoted_comma():
    assert parse_csv_line('1,"x,y",3') == ["1", "x,y", "3"]

def test_csv_trailing_empty():
    assert parse_csv_line("a,b,") == ["a", "b", ""]

def test_csv_single():
    assert parse_csv_line("only") == ["only"]

def test_csv_quoted_semicolon():
    assert parse_csv_line('"a;b",c') == ["a;b", "c"]
''', "CSV 行解析用裸 split，忽略引号内的分隔符"),

        V("parse_kv", "parsing", '''
def parse_kv(text):
    out = {}
    for part in text.split(","):
        if not part.strip():
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out
''', ("out[k.strip()] = v.strip()", "out[k] = v"),
          '''
from parsing import parse_kv

def test_kv_simple():
    assert parse_kv("a=1,b=2") == {"a": "1", "b": "2"}
''',
          '''
from parsing import parse_kv

def test_kv_spaces():
    assert parse_kv(" a = 1 , b = 2 ") == {"a": "1", "b": "2"}

def test_kv_empty_segments():
    assert parse_kv("a=1,,b=2") == {"a": "1", "b": "2"}

def test_kv_value_with_equal():
    assert parse_kv("a=b=c") == {"a": "b=c"}
''', "键值解析未去掉空白，带空格的输入产生错误键名"),

        V("parse_range", "parsing", '''
def parse_range(spec):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out
''', ("out.extend(range(int(a), int(b) + 1))", "out.append(int(a))"),
          '''
from parsing import parse_range

def test_range_simple():
    assert parse_range("1-3") == [1, 2, 3]
''',
          '''
from parsing import parse_range

def test_range_mixed():
    assert parse_range("1-3,5") == [1, 2, 3, 5]

def test_range_single_value():
    assert parse_range("7") == [7]

def test_range_empty():
    assert parse_range("") == []
''', "区间表达式只解析起点，丢弃整个区间"),

        V("parse_duration", "parsing", '''
def parse_duration(text):
    total = 0
    num = ""
    for ch in text:
        if ch.isdigit():
            num += ch
        else:
            if num:
                n = int(num)
                if ch == "h":
                    total += n * 3600
                elif ch == "m":
                    total += n * 60
                elif ch == "s":
                    total += n
                num = ""
    return total if num == "" else total + int(num)
''', ("elif ch == \"m\":\n                    total += n * 60", "elif ch == \"m\":\n                    total += n"),
          '''
from parsing import parse_duration

def test_duration_hours():
    assert parse_duration("2h") == 7200
''',
          '''
from parsing import parse_duration

def test_duration_hours_minutes():
    assert parse_duration("1h30m") == 5400

def test_duration_seconds():
    assert parse_duration("45s") == 45

def test_duration_minutes_only():
    assert parse_duration("5m") == 300

def test_duration_bare_seconds():
    assert parse_duration("10") == 10
''', "分钟单位按秒计算，时长被低估 60 倍"),

        V("parse_flags", "parsing", '''
def parse_flags(argv):
    out = {}
    for token in argv:
        if not token.startswith("--"):
            continue
        body = token[2:]
        if "=" in body:
            k, v = body.split("=", 1)
            out[k] = v
        else:
            out[body] = True
    return out
''', ("out[body] = True", "out[body] = \"true\""),
          '''
from parsing import parse_flags

def test_flags_pairs():
    assert parse_flags(["--a=1", "--b=2"]) == {"a": "1", "b": "2"}
''',
          '''
from parsing import parse_flags

def test_flag_boolean_type():
    assert parse_flags(["--verbose"]) == {"verbose": True}

def test_flag_ignores_positional():
    assert parse_flags(["file.txt", "--x"]) == {"x": True}

def test_flag_mixed():
    assert parse_flags(["--a", "--b=2"]) == {"a": True, "b": "2"}
''', "无值开关被解析成字符串 \"true\" 而不是布尔值"),

        V("parse_bool", "parsing", '''
def parse_bool(text):
    return str(text).strip().lower() in ("1", "true", "yes", "on")
''', ("return str(text).strip().lower() in (\"1\", \"true\", \"yes\", \"on\")", "return bool(text)"),
          '''
from parsing import parse_bool

def test_bool_true():
    assert parse_bool("yes") is True
''',
          '''
from parsing import parse_bool

def test_bool_false_string():
    assert parse_bool("false") is False

def test_bool_zero_string():
    assert parse_bool("0") is False

def test_bool_off():
    assert parse_bool("off") is False

def test_bool_true_variants():
    assert parse_bool("TRUE") is True
    assert parse_bool(" 1 ") is True
''', "布尔解析直接对原始字符串取真值，\"false\" 被判为真"),

        V("parse_float_list", "parsing", '''
def parse_float_list(text):
    if not text.strip():
        return []
    return [float(x) for x in text.split(",") if x.strip()]
''', ("return [float(x) for x in text.split(\",\") if x.strip()]", "return [float(x) for x in text.split(\",\")]"),
          '''
from parsing import parse_float_list

def test_floats_simple():
    assert parse_float_list("1.5,2.5") == [1.5, 2.5]
''',
          '''
from parsing import parse_float_list

def test_floats_empty_string():
    assert parse_float_list("") == []

def test_floats_double_comma():
    assert parse_float_list("1,,2") == [1.0, 2.0]

def test_floats_whitespace():
    assert parse_float_list("   ") == []

def test_floats_trailing():
    assert parse_float_list("1.0,") == [1.0]
''', "空片段没有被过滤，含连续逗号或尾逗号时抛 ValueError"),

        V("split_path", "parsing", '''
def split_path(path):
    out = []
    cur = ""
    in_quotes = False
    for ch in path:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "/" and not in_quotes:
            if cur:
                out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out
''', ("    out = []\n    cur = \"\"\n    in_quotes = False\n    for ch in path:\n        if ch == '\"':\n            in_quotes = not in_quotes\n        elif ch == \"/\" and not in_quotes:\n            if cur:\n                out.append(cur)\n            cur = \"\"\n        else:\n            cur += ch\n    if cur:\n        out.append(cur)\n    return out", "    return [p for p in path.split(\"/\") if p]"),
          '''
from parsing import split_path

def test_path_plain():
    assert split_path("a/b/c") == ["a", "b", "c"]
''',
          '''
from parsing import split_path

def test_path_quoted_slash():
    assert split_path('a/"b/c"/d') == ["a", "b/c", "d"]

def test_path_leading_slash():
    assert split_path("/a/b") == ["a", "b"]

def test_path_empty():
    assert split_path("") == []
''', "路径切分未处理引号，带引号且含斜杠的分段被拆散"),
    ],
}

F_RECURSION = {
    "name": "recursion",
    "bug_class": "递归基例错误",
    "variants": [
        V("flatten", "recursion", '''
def flatten(items):
    out = []
    for it in items:
        if isinstance(it, list):
            out.extend(flatten(it))
        else:
            out.append(it)
    return out
''', ("if isinstance(it, list):", "if isinstance(it, list) and it:"),
          '''
from recursion import flatten

def test_flatten_simple():
    assert flatten([1, [2, 3]]) == [1, 2, 3]
''',
          '''
from recursion import flatten

def test_flatten_empty_nested():
    assert flatten([1, [], [2, [3]]]) == [1, 2, 3]

def test_flatten_all_empty():
    assert flatten([[], [], []]) == []

def test_flatten_deep():
    assert flatten([1, [2, [3, [4]]]]) == [1, 2, 3, 4]
''', "递归条件漏掉空列表，空嵌套被当作叶子元素保留"),

        V("sum_nested", "recursion", '''
def sum_nested(x):
    if isinstance(x, list):
        return sum(sum_nested(i) for i in x)
    return x
''', ("    if isinstance(x, list):", "    if isinstance(x, list) and x:"),
          '''
from recursion import sum_nested

def test_sum_nested_simple():
    assert sum_nested([1, [2, [3]]]) == 6
''',
          '''
from recursion import sum_nested

def test_sum_empty_list():
    assert sum_nested([]) == 0

def test_sum_nested_empty_inner():
    assert sum_nested([[], []] ) == 0

def test_sum_plain_number():
    assert sum_nested(5) == 5

def test_sum_mixed():
    assert sum_nested([1, [2], 3]) == 6
''', "空列表被当作数值返回，求和得到列表而不是 0"),

        V("depth", "recursion", '''
def depth(x):
    if not isinstance(x, list):
        return 0
    if not x:
        return 1
    return 1 + max(depth(i) for i in x)
''', ("return 1 + max(depth(i) for i in x)", "return max(depth(i) for i in x)"),
          '''
from recursion import depth

def test_depth_simple():
    assert depth([1, 2]) == 1
''',
          '''
from recursion import depth

def test_depth_nested():
    assert depth([1, [2, [3]]]) == 3

def test_depth_empty():
    assert depth([]) == 1

def test_depth_scalar():
    assert depth(7) == 0

def test_depth_deep():
    assert depth([[[[]]]]) == 4
''', "递归深度少加了当前层，结果整体偏低 1"),

        V("count_nodes", "recursion", '''
def count_nodes(tree):
    if not isinstance(tree, dict):
        return 0
    return 1 + sum(count_nodes(v) for v in tree.values())
''', ("return 1 + sum(count_nodes(v) for v in tree.values())", "return sum(count_nodes(v) for v in tree.values())"),
          '''
from recursion import count_nodes

def test_count_simple():
    assert count_nodes({"a": 1}) == 1
''',
          '''
from recursion import count_nodes

def test_count_nested():
    assert count_nodes({"a": {"b": {}}}) == 3

def test_count_empty():
    assert count_nodes({}) == 1

def test_count_scalar():
    assert count_nodes(5) == 0
''', "节点计数漏算自身，根节点未被计入"),

        V("reverse_rec", "recursion", '''
def reverse_rec(s):
    if len(s) <= 1:
        return s
    return reverse_rec(s[1:]) + s[0]
''', ("return reverse_rec(s[1:]) + s[0]", "return s[0] + reverse_rec(s[1:])"),
          '''
from recursion import reverse_rec

def test_reverse_simple():
    assert reverse_rec("abc") == "cba"
''',
          '''
from recursion import reverse_rec

def test_reverse_single():
    assert reverse_rec("z") == "z"

def test_reverse_empty():
    assert reverse_rec("") == ""

def test_reverse_long():
    assert reverse_rec("abcdef") == "fedcba"
''', "递归拼接顺序反了，结果等于原串"),

        V("power", "recursion", '''
def power(base, exp):
    if exp == 0:
        return 1
    if exp % 2 == 1:
        return base * power(base, exp - 1)
    half = power(base, exp // 2)
    return half * half
''', ("    if exp % 2 == 1:", "    if exp > 1:"),
          '''
from recursion import power

def test_power_even():
    assert power(2, 4) == 16
''',
          '''
from recursion import power

def test_power_odd():
    assert power(2, 3) == 8

def test_power_zero():
    assert power(5, 0) == 1

def test_power_ten():
    assert power(2, 10) == 1024

def test_power_one():
    assert power(7, 1) == 7
''', "奇偶分支判断写成 exp>1，奇数次幂结果偏大"),

        V("to_binary", "recursion", '''
def to_binary(n):
    if n == 0:
        return "0"
    if n == 1:
        return "1"
    return to_binary(n // 2) + str(n % 2)
''', ("    if n == 0:\n        return \"0\"", "    if n == 0:\n        return \"\""),
          '''
from recursion import to_binary

def test_binary_simple():
    assert to_binary(2) == "10"
''',
          '''
from recursion import to_binary

def test_binary_zero():
    assert to_binary(0) == "0"

def test_binary_one():
    assert to_binary(1) == "1"

def test_binary_five():
    assert to_binary(5) == "101"

def test_binary_eight():
    assert to_binary(8) == "1000"
''', "n=0 的基例返回空串，导致 0 的二进制表示丢失"),

        V("tree_height", "recursion", '''
class Node:
    def __init__(self, value, children=None):
        self.value = value
        self.children = children or []


def tree_height(node):
    if node is None:
        return 0
    if not node.children:
        return 1
    return 1 + max(tree_height(c) for c in node.children)
''', ("    if not node.children:\n        return 1", "    if not node.children:\n        return 0"),
          '''
from recursion import Node, tree_height

def test_height_root_only():
    assert tree_height(Node(1)) == 1
''',
          '''
from recursion import Node, tree_height

def test_height_two_levels():
    root = Node(1, [Node(2), Node(3)])
    assert tree_height(root) == 2

def test_height_nested():
    root = Node(1, [Node(2, [Node(3)])])
    assert tree_height(root) == 3

def test_height_none():
    assert tree_height(None) == 0
''', "叶子节点高度返回 0，整棵树高度偏低 1"),
    ],
}

F_TYPES = {
    "name": "types",
    "bug_class": "类型转换/空值处理",
    "variants": [
        V("add_numbers", "normalize", '''
def add_numbers(a, b):
    return float(a) + float(b)
''', ("return float(a) + float(b)", "return a + b"),
          '''
from normalize import add_numbers

def test_add_ints():
    assert add_numbers(1, 2) == 3.0
''',
          '''
from normalize import add_numbers

def test_add_numeric_strings():
    assert add_numbers("1", "2") == 3.0

def test_add_mixed():
    assert add_numbers("3", 4) == 7.0

def test_add_floats():
    assert abs(add_numbers("1.5", "2.5") - 4.0) < 1e-9
''', "加法未做数值转换，两个字符串被拼接"),

        V("safe_int", "normalize", '''
def safe_int(value, default=0):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
''', ("return int(float(str(value).strip()))", "return int(value)"),
          '''
from normalize import safe_int

def test_safe_int_plain():
    assert safe_int("12") == 12
''',
          '''
from normalize import safe_int

def test_safe_int_float_string():
    assert safe_int("3.7") == 3

def test_safe_int_invalid():
    assert safe_int("abc", -1) == -1

def test_safe_int_none():
    assert safe_int(None, -5) == -5

def test_safe_int_padded():
    assert safe_int("  42 ") == 42
''', "safe_int 未先转 float，'3.7' 这类合法数字字符串走 default"),

        V("join_ids", "normalize", '''
def join_ids(ids):
    return ",".join(str(i) for i in ids)
''', ("return \",\".join(str(i) for i in ids)", "return \",\".join(ids)"),
          '''
from normalize import join_ids

def test_join_strings():
    assert join_ids(["a", "b"]) == "a,b"
''',
          '''
from normalize import join_ids

def test_join_ints():
    assert join_ids([1, 2, 3]) == "1,2,3"

def test_join_mixed():
    assert join_ids([1, "a"]) == "1,a"

def test_join_single():
    assert join_ids([7]) == "7"
''', "拼接未把元素转字符串，整型列表抛 TypeError"),

        V("format_price", "normalize", '''
def format_price(cents):
    return f"${cents / 100:.2f}"
''', ("return f\"${cents / 100:.2f}\"", "return f\"${cents / 100:.1f}\""),
          '''
from normalize import format_price

def test_price_whole():
    assert format_price(100) == "$1.00"
''',
          '''
from normalize import format_price

def test_price_cents():
    assert format_price(199) == "$1.99"

def test_price_small():
    assert format_price(5) == "$0.05"

def test_price_zero():
    assert format_price(0) == "$0.00"
''', "金额只保留 1 位小数，分值被抹掉"),

        V("sort_ids", "normalize", '''
def sort_ids(ids):
    return sorted(int(i) for i in ids)
''', ("return sorted(int(i) for i in ids)", "return sorted(ids)"),
          '''
from normalize import sort_ids

def test_sort_single_digit():
    assert sort_ids(["2", "1"]) == [1, 2]
''',
          '''
from normalize import sort_ids

def test_sort_numeric_order():
    assert sort_ids(["10", "2", "1"]) == [1, 2, 10]

def test_sort_negative():
    assert sort_ids(["-5", "3"]) == [-5, 3]

def test_sort_returns_ints():
    assert all(isinstance(x, int) for x in sort_ids(["4"]))
''', "排序按字符串字典序，\"10\" 排在 \"2\" 前"),

        V("total_amount", "normalize", '''
def total_amount(values):
    return sum(v for v in values if v is not None)
''', ("return sum(v for v in values if v is not None)", "return sum(values)"),
          '''
from normalize import total_amount

def test_total_plain():
    assert total_amount([1, 2]) == 3
''',
          '''
from normalize import total_amount

def test_total_with_none():
    assert total_amount([1, None, 3]) == 4

def test_total_all_none():
    assert total_amount([None, None]) == 0

def test_total_empty():
    assert total_amount([]) == 0

def test_total_with_zero():
    assert total_amount([0, 5]) == 5
''', "累加未过滤 None，遇到空值抛 TypeError"),

        V("count_nonnull", "normalize", '''
def count_nonnull(values):
    return sum(1 for v in values if v is not None)
''', ("return sum(1 for v in values if v is not None)", "return sum(1 for v in values if v)"),
          '''
from normalize import count_nonnull

def test_count_plain():
    assert count_nonnull([1, 2]) == 2
''',
          '''
from normalize import count_nonnull

def test_count_zero_counts():
    assert count_nonnull([0, 1, None]) == 2

def test_count_empty_string_counts():
    assert count_nonnull(["", "a"]) == 2

def test_count_all_none():
    assert count_nonnull([None]) == 0

def test_count_empty_list():
    assert count_nonnull([]) == 0
''', "把 \"非空\" 判断写成真值判断，0 和空串被漏计"),

        V("compare_values", "normalize", '''
def compare_values(a, b):
    a, b = float(a), float(b)
    return (a > b) - (a < b)
''', ("    a, b = float(a), float(b)\n", ""),
          '''
from normalize import compare_values

def test_compare_numbers():
    assert compare_values(2, 1) == 1
''',
          '''
from normalize import compare_values

def test_compare_numeric_strings():
    assert compare_values("10", "9") == 1

def test_compare_equal():
    assert compare_values("2", 2) == 0

def test_compare_negative():
    assert compare_values("-1", "0") == -1
''', "比较前未统一转数值，数字字符串按字典序比较出错"),
    ],
}
