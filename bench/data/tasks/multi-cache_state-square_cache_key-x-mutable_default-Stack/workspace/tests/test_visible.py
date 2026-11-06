
from state import SquareCache

def test_square_single():
    assert SquareCache().get(3) == 9



def test_square_distinct_values():
    c = SquareCache()
    assert c.get(2) == 4
    assert c.get(3) == 9
    assert c.get(2) == 4
