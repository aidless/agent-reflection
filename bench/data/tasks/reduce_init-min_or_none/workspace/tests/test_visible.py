
from stats import min_or_none

def test_min_basic():
    assert min_or_none([4, 1, 7]) == 1



def test_min_empty():
    assert min_or_none([]) is None
