
from state import LRUCache

def test_lru_put_get():
    c = LRUCache(2)
    c.put("a", 1)
    assert c.get("a") == 1



def test_lru_evicts_least_recently_used():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1
    c.put("c", 3)
    assert c.get("a") == 1
    assert c.get("b") is None
