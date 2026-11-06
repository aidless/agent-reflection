
from stats import clamp

def test_clamp_middle():
    assert clamp(5, 0, 10) == 5



def test_clamp_upper():
    assert clamp(14, 0, 10) == 10
