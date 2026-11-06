
from collect import append_tag

def test_append_basic():
    assert append_tag("a") == ["a"]



def test_no_leak_between_calls():
    first = append_tag("a")
    second = append_tag("b")
    assert first == ["a"]
    assert second == ["b"]
