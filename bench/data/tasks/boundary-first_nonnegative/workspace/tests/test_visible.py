
from search import first_nonnegative

def test_first_nonneg_middle():
    assert first_nonnegative([-3, -1, 0, 2]) == 2



def test_last_element_is_zero():
    assert first_nonnegative([-5, -2, 0]) == 2
