
from paging import between_inclusive

def test_between_basic():
    assert between_inclusive([0, 1, 2, 3, 4], 1, 3) == [1, 2, 3]



def test_between_adjacent():
    assert between_inclusive([0, 1, 2], 1, 2) == [1, 2]
