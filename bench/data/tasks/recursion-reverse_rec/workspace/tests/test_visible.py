
from recursion import reverse_rec

def test_reverse_simple():
    assert reverse_rec("abc") == "cba"



def test_reverse_long():
    assert reverse_rec("abcdef") == "fedcba"
