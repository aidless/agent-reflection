
from collect import collect_pairs

def test_pairs_basic():
    assert collect_pairs([(1, 2)]) == [(1, 2)]



def test_pairs_no_leak():
    a = collect_pairs([(1, 2)])
    b = collect_pairs([(3, 4)])
    assert a == [(1, 2)]
    assert b == [(3, 4)]
