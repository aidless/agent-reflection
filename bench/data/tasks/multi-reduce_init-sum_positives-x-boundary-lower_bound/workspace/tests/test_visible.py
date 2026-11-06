
from stats import sum_positives

def test_sum_positive_basic():
    assert sum_positives([1, -2, 3]) == 4



def test_sum_empty():
    assert sum_positives([]) == 0
