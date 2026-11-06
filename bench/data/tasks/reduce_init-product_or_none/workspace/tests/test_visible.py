
from stats import product_or_none

def test_product_basic():
    assert product_or_none([2, 3, 4]) == 24



def test_product_single():
    assert product_or_none([5]) == 5
