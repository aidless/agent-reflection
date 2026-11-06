
from state import BatchStats

def test_flush_mean():
    b = BatchStats()
    b.add(2)
    b.add(4)
    assert b.flush() == 3.0



def test_flush_clears():
    b = BatchStats()
    b.add(1)
    b.add(3)
    b.flush()
    assert b.flush() is None
