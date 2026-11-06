
from state import TokenBucket

def test_bucket_take():
    b = TokenBucket(3)
    assert b.take(2) is True



def test_bucket_refill_capped():
    b = TokenBucket(3)
    assert b.take(3) is True
    b.refill(10)
    assert b.tokens == 3
