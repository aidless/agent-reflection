
from collect import merge_defaults

def test_merge_basic():
    assert merge_defaults({"level": 3})["level"] == 3



def test_caller_dict_not_mutated():
    base = {"level": 1}
    out = merge_defaults({"level": 3}, base)
    assert base == {"level": 1}
    assert out["level"] == 3
