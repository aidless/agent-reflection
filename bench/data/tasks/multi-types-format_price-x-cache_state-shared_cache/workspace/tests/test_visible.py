
from normalize import format_price

def test_price_whole():
    assert format_price(100) == "$1.00"



def test_price_cents():
    assert format_price(199) == "$1.99"
