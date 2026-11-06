
from stats import max_or_none

def test_max_positive():
    assert max_or_none([3, 9, 4]) == 9



def test_max_all_negative():
    assert max_or_none([-5, -2, -9]) == -2
