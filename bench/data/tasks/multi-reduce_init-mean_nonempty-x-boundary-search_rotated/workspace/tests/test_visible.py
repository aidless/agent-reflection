
from stats import mean_nonempty

def test_mean_basic():
    assert mean_nonempty([2, 4, 6]) == 4.0



def test_mean_empty_none():
    assert mean_nonempty([]) is None
