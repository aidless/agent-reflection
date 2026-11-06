
from state import Config

def test_config_get_default():
    c = Config()
    assert c.get("x", 0) == 0



def test_set_invalidates_cache():
    c = Config()
    assert c.get("a") is None
    c.set("a", 1)
    assert c.get("a") == 1
    c.set("a", 2)
    assert c.get("a") == 2
