
from normalize import compare_values

def test_compare_numbers():
    assert compare_values(2, 1) == 1



def test_compare_numeric_strings():
    assert compare_values("10", "9") == 1
