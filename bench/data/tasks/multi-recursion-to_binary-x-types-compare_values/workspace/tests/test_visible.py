
from recursion import to_binary

def test_binary_simple():
    assert to_binary(2) == "10"



def test_binary_zero():
    assert to_binary(0) == "0"
