
from parsing import parse_bool

def test_bool_true():
    assert parse_bool("yes") is True



def test_bool_false_string():
    assert parse_bool("false") is False
