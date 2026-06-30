import pytest

from stocksync.providers import FinvizProvider, StockData
from tests import fixtures


@pytest.fixture()
def cache_file(tmp_path):
    return tmp_path / "cache.json"


def make_provider(cache_file, **overrides):
    counters = {"stock": 0}

    def get_stock(ticker):
        counters["stock"] += 1
        return dict(fixtures.AAPL_FUNDAMENTALS)

    defaults = dict(
        get_stock=get_stock,
        get_news=lambda t: list(fixtures.AAPL_NEWS),
        get_analyst_price_targets=lambda t: list(fixtures.AAPL_RATINGS),
        get_insider=lambda t: list(fixtures.AAPL_INSIDER),
        cache_path=cache_file,
        ttl_seconds=300,
    )
    defaults.update(overrides)
    provider = FinvizProvider(**defaults)
    return provider, counters


def test_fetch_assembles_all_feeds(cache_file):
    provider, _ = make_provider(cache_file)
    data = provider.fetch("aapl")
    assert data.ticker == "AAPL"
    assert data.company == "Apple Inc."
    assert data.fundamentals["P/E"] == "31.50"
    assert len(data.news) == 5
    assert len(data.analyst_ratings) == 2
    assert len(data.insider) == 3
    assert data.ok is True
    assert data.errors == []


def test_one_feed_failing_does_not_sink_others(cache_file):
    def boom(ticker):
        raise RuntimeError("insider feed down")

    provider, _ = make_provider(cache_file, get_insider=boom)
    data = provider.fetch("AAPL")
    assert data.ok is True  # fundamentals still loaded
    assert data.insider == []
    assert any("insider" in e for e in data.errors)


def test_caching_avoids_refetch(cache_file):
    clock = {"t": 1000.0}
    provider, counters = make_provider(cache_file, clock=lambda: clock["t"])
    provider.fetch("AAPL")
    provider.fetch("AAPL")
    assert counters["stock"] == 1  # second call served from cache


def test_cache_expires_after_ttl(cache_file):
    clock = {"t": 1000.0}
    provider, counters = make_provider(
        cache_file, clock=lambda: clock["t"], ttl_seconds=60
    )
    provider.fetch("AAPL")
    clock["t"] += 61  # advance past TTL
    provider.fetch("AAPL")
    assert counters["stock"] == 2


def test_no_cache_flag_forces_refetch(cache_file):
    provider, counters = make_provider(cache_file)
    provider.fetch("AAPL")
    provider.fetch("AAPL", use_cache=False)
    assert counters["stock"] == 2


def test_cache_persists_to_disk(cache_file):
    provider, _ = make_provider(cache_file)
    provider.fetch("AAPL")
    # A brand-new provider over the same file should read the warmed cache.
    provider2, counters2 = make_provider(cache_file)
    provider2.fetch("AAPL")
    assert counters2["stock"] == 0


def test_stockdata_roundtrip():
    data = StockData(
        ticker="AAPL",
        fundamentals={"Company": "Apple Inc."},
        news=[("t", "h", "u", "s")],
        fetched_at=123.0,
    )
    restored = StockData.from_dict(data.to_dict())
    assert restored.ticker == "AAPL"
    assert restored.news == [("t", "h", "u", "s")]
    assert restored.fetched_at == 123.0
