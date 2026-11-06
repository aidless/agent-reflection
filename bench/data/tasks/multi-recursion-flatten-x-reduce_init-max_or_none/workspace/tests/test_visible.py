
from recursion import flatten

def test_flatten_simple():
    assert flatten([1, [2, 3]]) == [1, 2, 3]



def test_flatten_empty_nested():
    assert flatten([1, [], [2, [3]]]) == [1, 2, 3]
