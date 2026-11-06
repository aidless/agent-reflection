
from paging import drop_head

def test_drop_basic():
    assert drop_head([1, 2, 3, 4], 2) == [3, 4]



def test_drop_all():
    assert drop_head([1, 2], 2) == []
