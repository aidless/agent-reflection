
from search import search_rotated

def test_rotated_plain():
    assert search_rotated([4, 5, 6, 7, 1, 2, 3], 2) == 5



def test_target_is_left_edge():
    assert search_rotated([4, 5, 6, 7, 1, 2, 3], 4) == 0
