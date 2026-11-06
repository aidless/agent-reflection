
from stats import argmax

def test_argmax_basic():
    assert argmax([1, 9, 3]) == 1



def test_argmax_first():
    assert argmax([9, 1]) == 0
