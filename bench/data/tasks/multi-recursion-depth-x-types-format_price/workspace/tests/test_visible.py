
from recursion import depth

def test_depth_simple():
    assert depth([1, 2]) == 1



def test_depth_nested():
    assert depth([1, [2, [3]]]) == 3
