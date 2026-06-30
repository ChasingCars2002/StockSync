import json

import pytest

from stocksync.watchlist import Watchlist


@pytest.fixture()
def wl(tmp_path):
    return Watchlist(path=tmp_path / "wl.json")


def test_add_and_contains(wl):
    assert wl.add("aapl") is True
    assert "AAPL" in wl
    assert "aapl" in wl  # case-insensitive
    assert len(wl) == 1


def test_add_duplicate_returns_false(wl):
    wl.add("AAPL")
    assert wl.add("AAPL") is False
    assert len(wl) == 1


def test_add_preserves_order(wl):
    for t in ("MSFT", "AAPL", "NVDA"):
        wl.add(t)
    assert wl.tickers == ["MSFT", "AAPL", "NVDA"]


def test_notes(wl):
    wl.add("AAPL", note="core holding")
    assert wl.note("AAPL") == "core holding"
    # Re-adding with a new note updates it but reports not-added.
    assert wl.add("AAPL", note="trimmed") is False
    assert wl.note("AAPL") == "trimmed"


def test_remove(wl):
    wl.add("AAPL")
    assert wl.remove("aapl") is True
    assert "AAPL" not in wl
    assert wl.remove("AAPL") is False


def test_empty_ticker_rejected(wl):
    with pytest.raises(ValueError):
        wl.add("   ")


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "wl.json"
    a = Watchlist(path=path)
    a.add("AAPL", note="n")
    b = Watchlist(path=path)
    assert b.tickers == ["AAPL"]
    assert b.note("AAPL") == "n"


def test_loads_bare_list_schema(tmp_path):
    path = tmp_path / "wl.json"
    path.write_text(json.dumps(["aapl", "msft"]))
    wl = Watchlist(path=path)
    assert wl.tickers == ["AAPL", "MSFT"]


def test_clear(wl):
    wl.add("AAPL")
    wl.add("MSFT")
    wl.clear()
    assert len(wl) == 0
