
from collect import group_by

def test_group_basic():
    assert group_by([1, 2, 3, 4], lambda x: x % 2) == {1: [1, 3], 0: [2, 4]}



def test_group_calls_independent():
    a = group_by([1, 2], lambda x: x % 2)
    b = group_by([10], lambda x: x % 2)
    assert a == {1: [1], 0: [2]}
    assert b == {0: [10]}
