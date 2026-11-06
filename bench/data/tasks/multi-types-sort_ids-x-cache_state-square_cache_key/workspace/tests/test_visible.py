
from normalize import sort_ids

def test_sort_single_digit():
    assert sort_ids(["2", "1"]) == [1, 2]



def test_sort_numeric_order():
    assert sort_ids(["10", "2", "1"]) == [1, 2, 10]
