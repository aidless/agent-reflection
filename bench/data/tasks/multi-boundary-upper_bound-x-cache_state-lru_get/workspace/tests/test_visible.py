
from search import upper_bound

def test_upper_bound_basic():
    assert upper_bound([1, 2, 2, 4], 2) == 3



def test_all_equal():
    assert upper_bound([2, 2, 2], 2) == 3
