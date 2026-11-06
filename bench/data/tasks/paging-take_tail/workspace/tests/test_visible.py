
from paging import take_tail

def test_tail_basic():
    assert take_tail([1, 2, 3, 4], 2) == [3, 4]
