
from stats import second_largest

def test_second_largest_basic():
    assert second_largest([3, 9, 1, 7]) == 7



def test_duplicates_max():
    assert second_largest([5, 5, 3]) == 3
