
from paging import page_items

def test_page_one():
    assert page_items(list(range(10)), 1, 3) == [0, 1, 2]



def test_page_two():
    assert page_items(list(range(10)), 2, 3) == [3, 4, 5]
