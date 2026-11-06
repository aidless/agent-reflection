
from paging import paginate_pairs

def test_pairs_basic():
    assert paginate_pairs([1, 2, 3, 4], 2) == [(1, [1, 2]), (3, [3, 4])]



def test_pairs_tail():
    assert paginate_pairs([1, 2, 3], 2) == [(1, [1, 2]), (3, [3])]
