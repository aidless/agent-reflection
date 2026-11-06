
from parsing import parse_csv_line

def test_csv_simple():
    assert parse_csv_line("a,b,c") == ["a", "b", "c"]



def test_csv_quoted_comma():
    assert parse_csv_line('1,"x,y",3') == ["1", "x,y", "3"]
