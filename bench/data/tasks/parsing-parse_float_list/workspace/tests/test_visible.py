
from parsing import parse_float_list

def test_floats_simple():
    assert parse_float_list("1.5,2.5") == [1.5, 2.5]



def test_floats_double_comma():
    assert parse_float_list("1,,2") == [1.0, 2.0]
