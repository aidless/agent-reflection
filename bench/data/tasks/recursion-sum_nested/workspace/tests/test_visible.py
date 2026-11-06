
from recursion import sum_nested

def test_sum_nested_simple():
    assert sum_nested([1, [2, [3]]]) == 6



def test_sum_empty_list():
    assert sum_nested([]) == 0
