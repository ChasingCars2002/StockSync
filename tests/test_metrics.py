from stocksync.metrics import (
    clamp,
    humanize_number,
    is_missing,
    parse_number,
    parse_percent,
)


def test_parse_number_suffixes():
    assert parse_number("1.23B") == 1_230_000_000.0
    assert parse_number("1.5M") == 1_500_000.0
    assert parse_number("3.4K") == 3_400.0
    assert parse_number("2T") == 2_000_000_000_000.0


def test_parse_number_decorations():
    assert parse_number("45.6%") == 45.6
    assert parse_number("$1,234.50") == 1234.50
    assert parse_number("  -12.5 ") == -12.5


def test_parse_number_missing():
    for v in ("-", "", "—", "n/a", None, "N/A"):
        assert parse_number(v) is None
        assert is_missing(v) is True


def test_parse_number_unparseable():
    assert parse_number("not a number") is None


def test_parse_percent_alias():
    assert parse_percent("12.5%") == 12.5


def test_humanize_number_roundtrip():
    assert humanize_number(1_230_000_000) == "1.23B"
    assert humanize_number(None) == "-"
    assert humanize_number(42) == "42.00"


def test_clamp():
    assert clamp(150) == 100
    assert clamp(-10) == 0
    assert clamp(55) == 55
