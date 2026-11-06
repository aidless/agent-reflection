
from stats import max_by_key

def test_max_by_key_basic():
    assert max_by_key(["aa", "bbbb", "c"], len) == "bbbb"



def test_max_by_key_dict():
    rows = [{"v": 1}, {"v": 9}, {"v": 5}]
    assert max_by_key(rows, lambda r: r["v"]) == {"v": 9}
