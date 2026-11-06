
from search import insert_position_desc

def test_insert_desc_basic():
    assert insert_position_desc([9, 7, 5, 3], 3) == 3



def test_insert_desc_last():
    assert insert_position_desc([9, 7, 5, 3], 2) == 4
