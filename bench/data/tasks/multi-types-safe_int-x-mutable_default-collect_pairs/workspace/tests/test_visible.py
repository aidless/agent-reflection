
from normalize import safe_int

def test_safe_int_plain():
    assert safe_int("12") == 12



def test_safe_int_float_string():
    assert safe_int("3.7") == 3
