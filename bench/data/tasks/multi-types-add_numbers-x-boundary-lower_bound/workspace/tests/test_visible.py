
from normalize import add_numbers

def test_add_ints():
    assert add_numbers(1, 2) == 3.0



def test_add_numeric_strings():
    assert add_numbers("1", "2") == 3.0
