
from normalize import count_nonnull

def test_count_plain():
    assert count_nonnull([1, 2]) == 2



def test_count_zero_counts():
    assert count_nonnull([0, 1, None]) == 2
