
from normalize import join_ids

def test_join_strings():
    assert join_ids(["a", "b"]) == "a,b"



def test_join_ints():
    assert join_ids([1, 2, 3]) == "1,2,3"
