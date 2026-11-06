
from search import count_occurrences

def test_count_basic():
    assert count_occurrences([1, 2, 2, 2, 3], 2) == 3



def test_count_absent_greater():
    assert count_occurrences([1, 2, 4], 5) == 0
