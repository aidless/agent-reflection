
from recursion import count_nodes

def test_count_simple():
    assert count_nodes({"a": 1}) == 1



def test_count_nested():
    assert count_nodes({"a": {"b": {}}}) == 3
