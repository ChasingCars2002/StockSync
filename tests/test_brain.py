from stocksync.brain import analyze, score_news
from stocksync.providers import StockData
from tests import fixtures


def make_data(fundamentals, news=None, insider=None):
    return StockData(
        ticker=fundamentals.get("Ticker", "TST"),
        fundamentals=dict(fundamentals),
        news=list(news or []),
        insider=list(insider or []),
    )


def test_strong_stock_scores_higher_than_risky():
    good = analyze(make_data(fixtures.AAPL_FUNDAMENTALS, fixtures.AAPL_NEWS))
    bad = analyze(make_data(fixtures.RISKY_FUNDAMENTALS, fixtures.NEGATIVE_NEWS))
    assert good.composite is not None and bad.composite is not None
    assert good.composite > bad.composite


def test_all_dimensions_present_for_full_fundamentals():
    a = analyze(make_data(fixtures.AAPL_FUNDAMENTALS))
    names = {d.name for d in a.dimensions if d.available}
    assert {"Valuation", "Profitability", "Growth", "Momentum", "Analyst", "Financial Health"} <= names


def test_dimension_score_in_range():
    a = analyze(make_data(fixtures.AAPL_FUNDAMENTALS))
    for d in a.dimensions:
        if d.available:
            assert 0.0 <= d.score <= 100.0


def test_missing_dimension_is_unavailable_not_zero():
    # Only a price, nothing else -> most dimensions have no data.
    a = analyze(make_data({"Ticker": "X", "Price": "10.00"}))
    val = a.dimension("Valuation")
    assert val is not None and val.available is False
    assert val.score is None


def test_composite_none_when_no_metrics():
    a = analyze(make_data({"Ticker": "X"}))
    assert a.composite is None
    assert a.verdict == "Insufficient data"


def test_analyst_upside_signal_bullish():
    a = analyze(make_data(fixtures.AAPL_FUNDAMENTALS))
    texts = " ".join(s.text for s in a.signals)
    assert "upside" in texts.lower()
    assert any(s.sentiment == "bullish" for s in a.signals)


def test_overbought_and_sell_signals_for_risky():
    a = analyze(make_data(fixtures.RISKY_FUNDAMENTALS))
    texts = " ".join(s.text for s in a.signals).lower()
    assert "overbought" in texts
    assert "sell" in texts
    assert any(s.sentiment == "bearish" for s in a.signals)


def test_insider_buying_signal():
    # AAPL fixture has 2 buys vs 1 sale -> net buying.
    a = analyze(make_data(fixtures.AAPL_FUNDAMENTALS, insider=fixtures.AAPL_INSIDER))
    assert any("insider buying" in s.text.lower() for s in a.signals)


def test_news_sentiment_positive():
    s = score_news(fixtures.AAPL_NEWS)
    assert s.score > 50
    assert s.label == "positive"
    assert s.positive >= s.negative


def test_news_sentiment_negative():
    s = score_news(fixtures.NEGATIVE_NEWS)
    assert s.score < 50
    assert s.label == "negative"


def test_news_sentiment_empty_is_neutral():
    s = score_news([])
    assert s.score == 50.0
    assert s.label == "no recent news"
    assert s.headlines_scored == 0


def test_verdict_thresholds():
    good = analyze(make_data(fixtures.AAPL_FUNDAMENTALS))
    assert good.verdict in {"Strong", "Favorable", "Neutral / Mixed"}
