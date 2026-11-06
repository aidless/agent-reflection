"""任务族 A（F1-F4）：每个变体含正确实现、可注入的 bug、可见测试、隐藏测试。

约定：bug 字段为 (原文片段, 替换片段)，生成器只替换第一次出现，从而得到有缺陷版本。
correct 源码同时作为自检基准（参考解），不暴露给 Agent。
"""
from __future__ import annotations


def V(name, module, correct, bug, visible, hidden, bug_desc):
    return {
        "name": name, "module": module, "correct": correct, "bug": bug,
        "visible": visible, "hidden": hidden, "bug_desc": bug_desc,
    }


F_BOUNDARY = {
    "name": "boundary",
    "bug_class": "二分/边界 off-by-one",
    "variants": [
        V("lower_bound", "search", '''
def lower_bound(arr, x):
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo
''', ("lo, hi = 0, len(arr)", "lo, hi = 0, len(arr) - 1"),
          '''
from search import lower_bound

def test_lower_bound_middle():
    assert lower_bound([1, 3, 5, 7], 5) == 2
''',
          '''
from search import lower_bound

def test_empty():
    assert lower_bound([], 5) == 0

def test_beyond_end():
    assert lower_bound([1, 3, 5], 6) == 3

def test_below_start():
    assert lower_bound([1, 3, 5], 0) == 0

def test_duplicates():
    assert lower_bound([1, 2, 2, 2, 3], 2) == 1
''', "lower_bound 的初始上界被写成 len-1，越界与重复元素时返回位置偏小"),

        V("upper_bound", "search", '''
def upper_bound(arr, x):
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo
''', ("if arr[mid] <= x:", "if arr[mid] < x:"),
          '''
from search import upper_bound

def test_upper_bound_basic():
    assert upper_bound([1, 2, 2, 4], 2) == 3
'''
          ,
          '''
from search import upper_bound

def test_no_match_greater():
    assert upper_bound([1, 2, 4], 3) == 2

def test_all_equal():
    assert upper_bound([2, 2, 2], 2) == 3

def test_empty():
    assert upper_bound([], 1) == 0
''', "upper_bound 把 <= 写成 <，重复元素后界错误"),

        V("insert_position_desc", "search", '''
def insert_position_desc(arr, x):
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] > x:
            lo = mid + 1
        else:
            hi = mid
    return lo
''', ("lo, hi = 0, len(arr)", "lo, hi = 0, len(arr) - 1"),
          '''
from search import insert_position_desc

def test_insert_desc_basic():
    assert insert_position_desc([9, 7, 5, 3], 3) == 3
''',
          '''
from search import insert_position_desc

def test_insert_desc_last():
    assert insert_position_desc([9, 7, 5, 3], 2) == 4

def test_insert_desc_first():
    assert insert_position_desc([9, 7, 5], 10) == 0

def test_desc_empty():
    assert insert_position_desc([], 1) == 0
''', "降序插入位置搜索的初始上界被写成 len-1"),

        V("count_occurrences", "search", '''
def lower_bound(arr, x):
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def upper_bound(arr, x):
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def count_occurrences(arr, x):
    return upper_bound(arr, x) - lower_bound(arr, x)
''', ("lo, hi = 0, len(arr)", "lo, hi = 0, len(arr) - 1"),
          '''
from search import count_occurrences

def test_count_basic():
    assert count_occurrences([1, 2, 2, 2, 3], 2) == 3
''',
          '''
from search import count_occurrences

def test_count_absent_greater():
    assert count_occurrences([1, 2, 4], 5) == 0

def test_count_all():
    assert count_occurrences([2, 2], 2) == 2

def test_count_empty():
    assert count_occurrences([], 7) == 0

def test_count_last_element():
    assert count_occurrences([1, 2, 3, 9], 9) == 1
''', "计数依赖 lower_bound，但其初始上界写成 len-1，末尾元素统计漏算"),

        V("first_nonnegative", "search", '''
def first_nonnegative(arr):
    for i, v in enumerate(arr):
        if v >= 0:
            return i
    return len(arr)
''', ("for i, v in enumerate(arr):", "for i, v in enumerate(arr[:-1]):"),
          '''
from search import first_nonnegative

def test_first_nonneg_middle():
    assert first_nonnegative([-3, -1, 0, 2]) == 2
''',
          '''
from search import first_nonnegative

def test_last_element_is_zero():
    assert first_nonnegative([-5, -2, 0]) == 2

def test_no_negative():
    assert first_nonnegative([1, 2]) == 0

def test_all_negative():
    assert first_nonnegative([-1, -2]) == 2

def test_empty():
    assert first_nonnegative([]) == 0
''', "线性扫描被误写成 arr[:-1]，最后一个元素被跳过"),

        V("last_le", "search", '''
def last_le(arr, x):
    pos = -1
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] <= x:
            pos = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return pos
''', ("pos = mid\n", "pos = mid + 1\n"),
          '''
from search import last_le

def test_last_le_middle():
    assert last_le([1, 3, 5, 7], 4) == 1
''',
          '''
from search import last_le

def test_last_le_all():
    assert last_le([1, 2], 99) == 1

def test_last_le_none():
    assert last_le([1, 2], 0) == -1

def test_last_le_duplicates():
    assert last_le([1, 2, 2, 2, 5], 2) == 3

def test_last_le_empty():
    assert last_le([], 5) == -1
''', "记录答案时下标被多加了 1"),

        V("search_rotated", "search", '''
def search_rotated(arr, target):
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        if arr[lo] <= arr[mid]:
            if arr[lo] <= target < arr[mid]:
                hi = mid - 1
            else:
                lo = mid + 1
        else:
            if arr[mid] < target <= arr[hi]:
                lo = mid + 1
            else:
                hi = mid - 1
    return -1
''', ("if arr[lo] <= target < arr[mid]:", "if arr[lo] < target <= arr[mid]:"),
          '''
from search import search_rotated

def test_rotated_plain():
    assert search_rotated([4, 5, 6, 7, 1, 2, 3], 2) == 5
''',
          '''
from search import search_rotated

def test_target_is_left_edge():
    assert search_rotated([4, 5, 6, 7, 1, 2, 3], 4) == 0

def test_target_missing():
    assert search_rotated([4, 5, 6, 7], 3) == -1

def test_single():
    assert search_rotated([7], 7) == 0

def test_target_is_right_edge():
    assert search_rotated([5, 1, 3], 3) == 2
''', "旋转数组二分中，目标等于左端点时被排除"),

        V("peak_index", "search", '''
def peak_index(arr):
    lo, hi = 0, len(arr) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] > arr[mid + 1]:
            hi = mid
        else:
            lo = mid + 1
    return lo
''', ("hi = mid\n", "hi = mid - 1\n"),
          '''
from search import peak_index

def test_peak_middle():
    assert peak_index([1, 3, 5, 4, 2]) == 2
''',
          '''
from search import peak_index

def test_peak_last():
    assert peak_index([1, 2, 3]) == 2

def test_peak_first():
    assert peak_index([5, 4, 1]) == 0

def test_single_element():
    assert peak_index([9]) == 0
''', "收缩右边界时多减 1，峰值在末尾时返回错误下标"),
    ],
}

F_PAGING = {
    "name": "paging",
    "bug_class": "切片/分页 off-by-one",
    "variants": [
        V("page_items", "paging", '''
def page_items(items, page, size):
    if page < 1 or size < 1:
        raise ValueError("page and size must be >= 1")
    start = (page - 1) * size
    return items[start:start + size]
''', ("start = (page - 1) * size", "start = page * size"),
          '''
from paging import page_items

def test_page_one():
    assert page_items(list(range(10)), 1, 3) == [0, 1, 2]
''',
          '''
from paging import page_items

def test_page_two():
    assert page_items(list(range(10)), 2, 3) == [3, 4, 5]

def test_last_partial():
    assert page_items(list(range(7)), 3, 3) == [6]

def test_beyond():
    assert page_items(list(range(5)), 5, 2) == []

def test_bad_args():
    import pytest
    with pytest.raises(ValueError):
        page_items([1], 0, 2)
''', "分页起始下标用了 page*size，整体错位一页"),

        V("chunk_list", "paging", '''
def chunk_list(items, n):
    if n < 1:
        raise ValueError("n must be >= 1")
    return [items[i:i + n] for i in range(0, len(items), n)]
''', ("range(0, len(items), n)", "range(0, len(items) - n, n)"),
          '''
from paging import chunk_list

def test_chunk_even():
    assert chunk_list([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
''',
          '''
from paging import chunk_list

def test_chunk_tail():
    assert chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

def test_chunk_single():
    assert chunk_list([1, 2, 3], 9) == [[1, 2, 3]]

def test_chunk_empty():
    assert chunk_list([], 2) == []
''', "分块循环终点少了 n，最后一块被丢掉"),

        V("sliding_window", "paging", '''
def sliding_window(items, k):
    if k < 1:
        raise ValueError("k must be >= 1")
    return [items[i:i + k] for i in range(len(items) - k + 1)]
''', ("range(len(items) - k + 1)", "range(len(items) - k)"),
          '''
from paging import sliding_window

def test_window_basic():
    assert sliding_window([1, 2, 3, 4], 2) == [[1, 2], [2, 3], [3, 4]]
''',
          '''
from paging import sliding_window

def test_window_full_length():
    assert sliding_window([1, 2, 3], 3) == [[1, 2, 3]]

def test_window_larger_than_list():
    assert sliding_window([1], 5) == []

def test_window_one():
    assert sliding_window([1, 2], 1) == [[1], [2]]
''', "窗口滑动次数少算一次，最后一个窗口缺失"),

        V("take_tail", "paging", '''
def take_tail(items, n):
    if n <= 0:
        return []
    return items[-n:]
''', ("return items[-n:]", "return items[-n - 1:]"),
          '''
from paging import take_tail

def test_tail_basic():
    assert take_tail([1, 2, 3, 4], 2) == [3, 4]
''',
          '''
from paging import take_tail

def test_tail_all():
    assert take_tail([1, 2], 5) == [1, 2]

def test_tail_zero():
    assert take_tail([1, 2], 0) == []

def test_tail_exact():
    assert take_tail([1, 2, 3], 3) == [1, 2, 3]
''', "取尾部多取了 1 个元素"),

        V("drop_head", "paging", '''
def drop_head(items, n):
    if n <= 0:
        return list(items)
    return items[n:]
''', ("return items[n:]", "return items[n - 1:]"),
          '''
from paging import drop_head

def test_drop_basic():
    assert drop_head([1, 2, 3, 4], 2) == [3, 4]
''',
          '''
from paging import drop_head

def test_drop_all():
    assert drop_head([1, 2], 2) == []

def test_drop_zero():
    assert drop_head([1, 2], 0) == [1, 2]

def test_drop_one():
    assert drop_head([1, 2, 3], 1) == [2, 3]
''', "丢弃前 n 个被写成 n-1 个"),

        V("between_inclusive", "paging", '''
def between_inclusive(items, lo, hi):
    if hi < lo:
        return []
    return items[lo:hi + 1]
''', ("return items[lo:hi + 1]", "return items[lo:hi]"),
          '''
from paging import between_inclusive

def test_between_basic():
    assert between_inclusive([0, 1, 2, 3, 4], 1, 3) == [1, 2, 3]
''',
          '''
from paging import between_inclusive

def test_between_adjacent():
    assert between_inclusive([0, 1, 2], 1, 2) == [1, 2]

def test_between_same():
    assert between_inclusive([0, 1, 2], 1, 1) == [1]

def test_between_reverse():
    assert between_inclusive([0, 1, 2], 2, 1) == []
''', "闭区间切片写成半开区间，右端点丢一个"),

        V("last_page", "paging", '''
def last_page(total, size):
    if size < 1:
        raise ValueError("size must be >= 1")
    return (total + size - 1) // size
''', ("return (total + size - 1) // size", "return total // size"),
          '''
from paging import last_page

def test_last_page_exact():
    assert last_page(10, 5) == 2
''',
          '''
from paging import last_page

def test_last_page_partial():
    assert last_page(11, 5) == 3

def test_last_page_zero():
    assert last_page(0, 5) == 0

def test_last_page_less_than_size():
    assert last_page(3, 5) == 1
''', "末页编号用向下取整，存在余数时少一页"),

        V("paginate_pairs", "paging", '''
def paginate_pairs(items, size):
    if size < 1:
        raise ValueError("size must be >= 1")
    out = []
    start = 0
    while start < len(items):
        out.append((start + 1, items[start:start + size]))
        start += size
    return out
''', ("while start < len(items):", "while start < len(items) - size:"),
          '''
from paging import paginate_pairs

def test_pairs_basic():
    assert paginate_pairs([1, 2, 3, 4], 2) == [(1, [1, 2]), (3, [3, 4])]
''',
          '''
from paging import paginate_pairs

def test_pairs_tail():
    assert paginate_pairs([1, 2, 3], 2) == [(1, [1, 2]), (3, [3])]

def test_pairs_empty():
    assert paginate_pairs([], 2) == []

def test_pairs_single_pass():
    assert paginate_pairs([1], 5) == [(1, [1])]
''', "分页循环条件少算了最后一块"),
    ],
}

F_REDUCE = {
    "name": "reduce_init",
    "bug_class": "归约初值/比较器错误",
    "variants": [
        V("max_or_none", "stats", '''
def max_or_none(values):
    if not values:
        return None
    best = values[0]
    for v in values[1:]:
        if v > best:
            best = v
    return best
''', ("best = values[0]", "best = 0"),
          '''
from stats import max_or_none

def test_max_positive():
    assert max_or_none([3, 9, 4]) == 9
''',
          '''
from stats import max_or_none

def test_max_all_negative():
    assert max_or_none([-5, -2, -9]) == -2

def test_max_single_negative():
    assert max_or_none([-7]) == -7

def test_max_empty():
    assert max_or_none([]) is None

def test_max_zero_included():
    assert max_or_none([-3, 0, -1]) == 0
''', "求最大值用 0 作初值，全负数组返回 0"),

        V("min_or_none", "stats", '''
def min_or_none(values):
    if not values:
        return None
    best = values[0]
    for v in values[1:]:
        if v < best:
            best = v
    return best
''', ("if not values:\n        return None", "if not values:\n        return float(\"inf\")"),
          '''
from stats import min_or_none

def test_min_basic():
    assert min_or_none([4, 1, 7]) == 1
''',
          '''
from stats import min_or_none

def test_min_empty():
    assert min_or_none([]) is None

def test_min_negative():
    assert min_or_none([3, -4, 2]) == -4

def test_min_single():
    assert min_or_none([8]) == 8
''', "空输入时返回 inf 而不是 None"),

        V("second_largest", "stats", '''
def second_largest(values):
    if len(values) < 2:
        return None
    uniq = sorted(set(values), reverse=True)
    return uniq[1] if len(uniq) >= 2 else None
''', ("uniq = sorted(set(values), reverse=True)", "uniq = sorted(values, reverse=True)"),
          '''
from stats import second_largest

def test_second_largest_basic():
    assert second_largest([3, 9, 1, 7]) == 7
''',
          '''
from stats import second_largest

def test_duplicates_max():
    assert second_largest([5, 5, 3]) == 3

def test_all_same():
    assert second_largest([4, 4, 4]) is None

def test_two_items():
    assert second_largest([1, 2]) == 1

def test_too_short():
    assert second_largest([9]) is None
''', "第二大的去重被去掉，重复最大值时返回最大值"),

        V("argmax", "stats", '''
def argmax(values):
    if not values:
        return None
    best_i, best_v = 0, values[0]
    for i, v in enumerate(values[1:], start=1):
        if v > best_v:
            best_i, best_v = i, v
    return best_i
''', ("return best_i", "return best_v"),
          '''
from stats import argmax

def test_argmax_basic():
    assert argmax([1, 9, 3]) == 1
''',
          '''
from stats import argmax

def test_argmax_first():
    assert argmax([9, 1]) == 0

def test_argmax_last():
    assert argmax([1, 2, 8]) == 2

def test_argmax_empty():
    assert argmax([]) is None

def test_argmax_equal():
    assert argmax([3, 3]) == 0
''', "argmax 返回最大值本身而不是下标"),

        V("clamp", "stats", '''
def clamp(value, lo, hi):
    if hi < lo:
        raise ValueError("hi must be >= lo")
    return max(lo, min(hi, value))
''', ("return max(lo, min(hi, value))", "return min(lo, max(hi, value))"),
          '''
from stats import clamp

def test_clamp_middle():
    assert clamp(5, 0, 10) == 5
''',
          '''
from stats import clamp

def test_clamp_upper():
    assert clamp(14, 0, 10) == 10

def test_clamp_lower():
    assert clamp(-3, 0, 10) == 0

def test_clamp_bad_range():
    import pytest
    with pytest.raises(ValueError):
        clamp(5, 10, 0)
''', "clamp 的 min/max 顺序颠倒，越界时返回错误边界"),

        V("mean_nonempty", "stats", '''
def mean_nonempty(values):
    if not values:
        return None
    return sum(values) / len(values)
''', ("    if not values:\n        return None\n", "    # if not values: return None\n"),
          '''
from stats import mean_nonempty

def test_mean_basic():
    assert mean_nonempty([2, 4, 6]) == 4.0
''',
          '''
from stats import mean_nonempty

def test_mean_empty_none():
    assert mean_nonempty([]) is None

def test_mean_single():
    assert mean_nonempty([5]) == 5.0

def test_mean_float():
    assert abs(mean_nonempty([1.5, 2.5]) - 2.0) < 1e-9
''', "空输入保护被注释掉，空列表抛 ZeroDivisionError"),

        V("max_by_key", "stats", '''
def max_by_key(items, key):
    if not items:
        return None
    best = items[0]
    for it in items[1:]:
        if key(it) > key(best):
            best = it
    return best
''', ("if key(it) > key(best):", "if it > best:"),
          '''
from stats import max_by_key

def test_max_by_key_basic():
    assert max_by_key(["aa", "bbbb", "c"], len) == "bbbb"
''',
          '''
from stats import max_by_key

def test_max_by_key_dict():
    rows = [{"v": 1}, {"v": 9}, {"v": 5}]
    assert max_by_key(rows, lambda r: r["v"]) == {"v": 9}

def test_max_by_key_empty():
    assert max_by_key([], len) is None

def test_max_by_key_tie():
    assert max_by_key(["bb", "aa"], len) == "bb"
''', "max_by_key 直接比较元素本身，忽略 key 函数"),

        V("sum_positives", "stats", '''
def sum_positives(values):
    total = 0
    for v in values:
        if v > 0:
            total += v
    return total
''', ("total = 0\n", "total = 1\n"),
          '''
from stats import sum_positives

def test_sum_positive_basic():
    assert sum_positives([1, -2, 3]) == 4
''',
          '''
from stats import sum_positives

def test_sum_empty():
    assert sum_positives([]) == 0

def test_sum_all_negative():
    assert sum_positives([-1, -2]) == 0

def test_sum_zero_only():
    assert sum_positives([0, 0]) == 0
''', "求和初值写成 1，空数组与全非正输入返回 1"),

        V("product_or_none", "stats", '''
def product_or_none(values):
    if not values:
        return None
    out = 1
    for v in values:
        out *= v
    return out
''', ("out = 1\n", "out = 0\n"),
          '''
from stats import product_or_none

def test_product_basic():
    assert product_or_none([2, 3, 4]) == 24
''',
          '''
from stats import product_or_none

def test_product_empty():
    assert product_or_none([]) is None

def test_product_single():
    assert product_or_none([5]) == 5

def test_product_with_zero():
    assert product_or_none([2, 0, 3]) == 0
''', "乘积初值写成 0，所有结果都变 0"),
    ],
}

F_MUTABLE = {
    "name": "mutable_default",
    "bug_class": "可变默认参数/共享状态",
    "variants": [
        V("append_tag", "collect", '''
def append_tag(tag, tags=None):
    if tags is None:
        tags = []
    tags.append(tag)
    return tags
''', ("def append_tag(tag, tags=None):", "def append_tag(tag, tags=[]):"),
          '''
from collect import append_tag

def test_append_basic():
    assert append_tag("a") == ["a"]
''',
          '''
from collect import append_tag

def test_no_leak_between_calls():
    first = append_tag("a")
    second = append_tag("b")
    assert first == ["a"]
    assert second == ["b"]

def test_explicit_list_reused():
    box = ["x"]
    assert append_tag("y", box) == ["x", "y"]
''', "可变默认参数列表在多次调用间共享"),

        V("group_by", "collect", '''
def group_by(items, key):
    out = {}
    for it in items:
        out.setdefault(key(it), []).append(it)
    return out
''', ("def group_by(items, key):\n    out = {}", "def group_by(items, key, out={}):"),
          '''
from collect import group_by

def test_group_basic():
    assert group_by([1, 2, 3, 4], lambda x: x % 2) == {1: [1, 3], 0: [2, 4]}
''',
          '''
from collect import group_by

def test_group_calls_independent():
    a = group_by([1, 2], lambda x: x % 2)
    b = group_by([10], lambda x: x % 2)
    assert a == {1: [1], 0: [2]}
    assert b == {0: [10]}

def test_group_empty():
    assert group_by([], lambda x: x) == {}
''', "分组结果放进模块级缓存字典，两次调用互相污染"),

        V("unique_append", "collect", '''
def unique_append(items, value, seen=None):
    if seen is None:
        seen = set()
    if value in seen:
        return list(items)
    seen.add(value)
    return list(items) + [value]
''', ("def unique_append(items, value, seen=None):", "def unique_append(items, value, seen=set()):"),
          '''
from collect import unique_append

def test_unique_basic():
    assert unique_append([1, 2], 3) == [1, 2, 3]
''',
          '''
from collect import unique_append

def test_unique_leak():
    first = unique_append([], 7)
    second = unique_append([], 7)
    assert first == [7]
    assert second == [7]

def test_unique_duplicate_in_list():
    assert unique_append([1], 1, {1}) == [1]
''', "去重集合作为可变默认参数，跨调用残留"),

        V("collect_pairs", "collect", '''
def collect_pairs(rows):
    out = []
    for a, b in rows:
        out.append((a, b))
    return out
''', ("def collect_pairs(rows):\n    out = []", "def collect_pairs(rows, out=[]):"),
          '''
from collect import collect_pairs

def test_pairs_basic():
    assert collect_pairs([(1, 2)]) == [(1, 2)]
''',
          '''
from collect import collect_pairs

def test_pairs_no_leak():
    a = collect_pairs([(1, 2)])
    b = collect_pairs([(3, 4)])
    assert a == [(1, 2)]
    assert b == [(3, 4)]

def test_pairs_empty():
    assert collect_pairs([]) == []
''', "输出列表作为可变默认参数，多次调用累积"),

        V("make_counter", "collect", '''
def make_counter():
    state = {"n": 0}

    def inc():
        state["n"] += 1
        return state["n"]

    return inc
''', ("state[\"n\"] += 1\n        return state[\"n\"]", "n = state[\"n\"]\n        state[\"n\"] += 1\n        return n"),
          '''
from collect import make_counter

def test_counter_basic():
    c = make_counter()
    assert c() == 1
''',
          '''
from collect import make_counter

def test_counter_increments():
    c = make_counter()
    assert [c(), c(), c()] == [1, 2, 3]

def test_counters_isolated():
    a, b = make_counter(), make_counter()
    a()
    assert b() == 1
''', "计数器返回值取自局部快照，连续调用总返回 1"),

        V("Stack", "collect", '''
class Stack:
    def __init__(self):
        self.items = []

    def push(self, x):
        self.items.append(x)

    def pop(self):
        if not self.items:
            raise IndexError("pop from empty stack")
        return self.items.pop()

    def size(self):
        return len(self.items)
''', ("    def __init__(self):\n        self.items = []", "    items = []\n\n    def __init__(self):\n        pass"),
          '''
from collect import Stack

def test_stack_basic():
    s = Stack()
    s.push(1)
    assert s.pop() == 1
''',
          '''
from collect import Stack

def test_stack_instances_isolated():
    a, b = Stack(), Stack()
    a.push(1)
    assert b.size() == 0
    assert a.size() == 1

def test_stack_empty_pop():
    import pytest
    with pytest.raises(IndexError):
        Stack().pop()
''', "类属性 _shared 被所有实例共享，栈之间互相污染"),

        V("merge_defaults", "collect", '''
def merge_defaults(overrides, defaults=None):
    if defaults is None:
        defaults = {"level": 1, "tags": []}
    out = dict(defaults)
    out.update(overrides)
    return out
''', ("out = dict(defaults)", "out = defaults"),
          '''
from collect import merge_defaults

def test_merge_basic():
    assert merge_defaults({"level": 3})["level"] == 3
''',
          '''
from collect import merge_defaults

def test_defaults_not_polluted():
    merge_defaults({"level": 3})
    assert merge_defaults({})["level"] == 1

def test_caller_dict_not_mutated():
    base = {"level": 1}
    out = merge_defaults({"level": 3}, base)
    assert base == {"level": 1}
    assert out["level"] == 3

def test_nested_tags_copied():
    base = {"tags": ["a"]}
    out = merge_defaults({"tags": ["b"]}, base)
    assert base["tags"] == ["a"]
''', "输出直接引用传入的 defaults 字典，覆盖时污染调用方数据"),

        V("add_metric", "collect", '''
def add_metric(name, value, store=None):
    if store is None:
        store = {}
    store.setdefault(name, []).append(value)
    return store
''', ("def add_metric(name, value, store=None):", "def add_metric(name, value, store={}):"),
          '''
from collect import add_metric

def test_metric_basic():
    assert add_metric("x", 1) == {"x": [1]}
''',
          '''
from collect import add_metric

def test_metric_no_leak():
    first = add_metric("x", 1)
    second = add_metric("y", 2)
    assert first == {"x": [1]}
    assert second == {"y": [2]}

def test_metric_explicit_store():
    store = {}
    add_metric("x", 1, store)
    add_metric("x", 2, store)
    assert store == {"x": [1, 2]}

def test_metric_empty_call():
    assert add_metric("x", 0) == {"x": [0]}
''', "指标字典作为可变默认参数，跨调用累积"),
    ],
}
