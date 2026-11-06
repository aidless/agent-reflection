
from collect import make_counter

def test_counter_basic():
    c = make_counter()
    assert c() == 1



def test_counter_increments():
    c = make_counter()
    assert [c(), c(), c()] == [1, 2, 3]
