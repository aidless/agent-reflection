
from collect import unique_append

def test_unique_basic():
    assert unique_append([1, 2], 3) == [1, 2, 3]



def test_unique_leak():
    first = unique_append([], 7)
    second = unique_append([], 7)
    assert first == [7]
    assert second == [7]
