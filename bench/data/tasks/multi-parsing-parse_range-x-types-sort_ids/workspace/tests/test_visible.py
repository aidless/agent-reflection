
from parsing import parse_range

def test_range_simple():
    assert parse_range("1-3") == [1, 2, 3]



def test_range_mixed():
    assert parse_range("1-3,5") == [1, 2, 3, 5]
