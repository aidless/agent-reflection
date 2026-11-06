
from collect import add_metric

def test_metric_basic():
    assert add_metric("x", 1) == {"x": [1]}



def test_metric_no_leak():
    first = add_metric("x", 1)
    second = add_metric("y", 2)
    assert first == {"x": [1]}
    assert second == {"y": [2]}
