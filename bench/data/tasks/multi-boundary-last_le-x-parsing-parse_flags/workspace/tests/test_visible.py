
from search import last_le

def test_last_le_middle():
    assert last_le([1, 3, 5, 7], 4) == 1



def test_last_le_all():
    assert last_le([1, 2], 99) == 1
