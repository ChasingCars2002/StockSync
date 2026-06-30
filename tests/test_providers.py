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


def test_fetch_movers_normalizes_and_excludes(cache_file):
    rows = [
        {"Ticker": "GME", "Company": "GameStop", "Price": "30", "Change": "12%", "Volume": "9M"},
        {"Ticker": "AAPL", "Company": "Apple", "Price": "195", "Change": "1%", "Volume": "1M"},
        {"Ticker": "AMC", "Company": "AMC", "Price": "5", "Change": "8%", "Volume": "5M"},
    ]
    provider = FinvizProvider(
        get_screener=lambda sig, lim: rows,
        cache_path=cache_file,
    )
    movers = provider.fetch_movers("ta_topgainers", limit=10, exclude=["AAPL"])
    tickers = [m["ticker"] for m in movers]
    assert "AAPL" not in tickers          # excluded (on watchlist)
    assert tickers == ["GME", "AMC"]
    assert movers[0]["company"] == "GameStop"
    assert movers[0]["change"] == "12%"


def test_fetch_movers_limit(cache_file):
    rows = [{"Ticker": f"T{i}", "Price": "1", "Change": "1%"} for i in range(20)]
    provider = FinvizProvider(get_screener=lambda sig, lim: rows, cache_path=cache_file)
    assert len(provider.fetch_movers("ta_topgainers", limit=5)) == 5


def test_fetch_movers_failure_is_empty(cache_file):
    def boom(sig, lim):
        raise RuntimeError("screener down")

    provider = FinvizProvider(get_screener=boom, cache_path=cache_file)
    assert provider.fetch_movers("ta_topgainers") == []


def test_fetch_movers_caches(cache_file):
    calls = {"n": 0}

    def screener(sig, lim):
        calls["n"] += 1
        return [{"Ticker": "GME", "Price": "1", "Change": "1%"}]

    clock = {"t": 1000.0}
    provider = FinvizProvider(
        get_screener=screener, cache_path=cache_file, clock=lambda: clock["t"], ttl_seconds=300
    )
    provider.fetch_movers("ta_topgainers")
    provider.fetch_movers("ta_topgainers")
    assert calls["n"] == 1  # second call served from cache


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
