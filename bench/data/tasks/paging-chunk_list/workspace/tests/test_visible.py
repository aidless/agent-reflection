
from paging import chunk_list

def test_chunk_even():
    assert chunk_list([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]



def test_chunk_tail():
    assert chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
