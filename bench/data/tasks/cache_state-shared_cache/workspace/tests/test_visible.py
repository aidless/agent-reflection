
from state import Memo

def test_memo_basic():
    assert Memo().compute(2) == 6



def test_cache_not_shared_across_instances():
    a = Memo()
    a.compute(1)
    a.compute(2)
    b = Memo()
    assert len(b.cache) == 0
