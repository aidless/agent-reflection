
from state import TTLCache

def test_ttl_immediate():
    c = TTLCache(10)
    c.set("a", 1)
    assert c.get("a") == 1

import time

def test_ttl_expires():
    c = TTLCache(0.05)
    c.set("a", 1)
    time.sleep(0.12)
    assert c.get("a") is None
