
from paging import sliding_window

def test_window_basic():
    assert sliding_window([1, 2, 3, 4], 2) == [[1, 2], [2, 3], [3, 4]]



def test_window_full_length():
    assert sliding_window([1, 2, 3], 3) == [[1, 2, 3]]
