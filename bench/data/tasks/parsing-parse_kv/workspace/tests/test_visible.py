
from parsing import parse_kv

def test_kv_simple():
    assert parse_kv("a=1,b=2") == {"a": "1", "b": "2"}



def test_kv_spaces():
    assert parse_kv(" a = 1 , b = 2 ") == {"a": "1", "b": "2"}
