
from parsing import parse_flags

def test_flags_pairs():
    assert parse_flags(["--a=1", "--b=2"]) == {"a": "1", "b": "2"}



def test_flag_boolean_type():
    assert parse_flags(["--verbose"]) == {"verbose": True}
