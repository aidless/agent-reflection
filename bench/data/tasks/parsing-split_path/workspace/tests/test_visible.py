
from parsing import split_path

def test_path_plain():
    assert split_path("a/b/c") == ["a", "b", "c"]



def test_path_quoted_slash():
    assert split_path('a/"b/c"/d') == ["a", "b/c", "d"]
