
from paging import last_page

def test_last_page_exact():
    assert last_page(10, 5) == 2



def test_last_page_partial():
    assert last_page(11, 5) == 3
