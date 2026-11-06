
from normalize import total_amount

def test_total_plain():
    assert total_amount([1, 2]) == 3



def test_total_with_none():
    assert total_amount([1, None, 3]) == 4
