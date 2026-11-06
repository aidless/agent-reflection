
from parsing import parse_duration

def test_duration_hours():
    assert parse_duration("2h") == 7200



def test_duration_hours_minutes():
    assert parse_duration("1h30m") == 5400
