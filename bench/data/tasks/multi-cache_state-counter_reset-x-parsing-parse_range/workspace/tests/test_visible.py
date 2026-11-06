
from state import Counter

def test_counter_add():
    c = Counter()
    assert c.add(2) == 2



def test_reset_clears():
    c = Counter()
    c.add(5)
    c.reset()
    assert c.add(1) == 1
