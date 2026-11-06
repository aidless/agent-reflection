
from search import lower_bound

def test_lower_bound_middle():
    assert lower_bound([1, 3, 5, 7], 5) == 2



def test_beyond_end():
    assert lower_bound([1, 3, 5], 6) == 3
