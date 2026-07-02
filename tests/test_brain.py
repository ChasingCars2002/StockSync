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


def test_quality_score_excludes_momentum():
    # A stock with weak fundamentals but a huge up-day should NOT earn a high
    # quality score even though its momentum/composite get a boost.
    hot_but_weak = {
        "Ticker": "HOT",
        "Price": "10.00",
        "Change": "25.00%",
        "P/E": "200.00",          # very expensive
        "PEG": "8.00",
        "Profit Margin": "-20.00%",  # unprofitable
        "ROE": "-10.00%",
        "EPS next 5Y": "-5.00%",
        "Recom": "3.50",
        "RSI (14)": "85.00",      # screaming momentum
        "SMA200": "60.00%",       # far above the 200-day
        "Perf Year": "300.00%",
        "Debt/Eq": "5.00",
    }
    a = analyze(make_data(hot_but_weak))
    mom = a.dimension("Momentum")
    assert mom is not None and mom.available and mom.score >= 70  # momentum is hot
    assert a.quality_score is not None
    assert a.quality_score < 40  # but quality (momentum-excluded) is poor


def test_quality_score_high_for_strong_fundamentals():
    a = analyze(make_data(fixtures.AAPL_FUNDAMENTALS))
    assert a.quality_score is not None and a.quality_score >= 50


def test_verdict_thresholds():
    good = analyze(make_data(fixtures.AAPL_FUNDAMENTALS))
    assert good.verdict in {"Strong", "Favorable", "Neutral / Mixed"}


# ---------------------------------------------------------------------------
# Risk assessment
# ---------------------------------------------------------------------------

def test_risk_higher_for_risky_stock():
    good = analyze(make_data(fixtures.AAPL_FUNDAMENTALS))
    bad = analyze(make_data(fixtures.RISKY_FUNDAMENTALS))
    assert good.risk is not None and bad.risk is not None
    assert bad.risk.score > good.risk.score
    assert bad.risk.level in {"Elevated", "High"}
    assert good.risk.level in {"Low", "Moderate"}


def test_risk_factors_are_explained():
    a = analyze(make_data(fixtures.RISKY_FUNDAMENTALS))
    text = " ".join(a.risk.factors).lower()
    # The shorted, levered, unprofitable fixture should name its problems.
    assert "short" in text
    assert "leverage" in text or "debt" in text
    assert "unprofitable" in text or "margin" in text


def test_risk_levels_cover_all_scores():
    from stocksync.brain import assess_risk
    calm = assess_risk({"Beta": "0.5", "Debt/Eq": "0.1", "Profit Margin": "25%"})
    wild = assess_risk({
        "Beta": "2.5", "Short Float": "25%", "Debt/Eq": "4.0",
        "Profit Margin": "-30%", "Price": "2.50", "Volatility": "9.1% 10.2%",
    })
    assert calm.level == "Low"
    assert wild.level == "High"
    assert 0 <= calm.score < wild.score <= 100


# ---------------------------------------------------------------------------
# Strengths, concerns and thesis
# ---------------------------------------------------------------------------

def test_strengths_and_concerns_carry_numbers():
    a = analyze(make_data(fixtures.AAPL_FUNDAMENTALS))
    assert a.strengths, "AAPL fixture should surface strengths"
    # ROE 150% is the standout fact and should appear with its number.
    assert any("150" in s for s in a.strengths)
    # The rich P/B / PEG should register as a concern or leave concerns valid.
    assert all(isinstance(c, str) and c for c in a.concerns)


def test_concerns_for_weak_stock():
    a = analyze(make_data(fixtures.RISKY_FUNDAMENTALS))
    assert a.concerns
    text = " ".join(a.concerns).lower()
    assert "losing money" in text or "roe" in text or "shrink" in text


def test_thesis_mentions_ticker_and_risk():
    a = analyze(make_data(fixtures.AAPL_FUNDAMENTALS, fixtures.AAPL_NEWS))
    assert a.thesis
    assert "AAPL" in a.thesis
    assert "risk" in a.thesis.lower()
    assert "news flow" in a.thesis.lower()


def test_thesis_insufficient_data():
    a = analyze(make_data({"Ticker": "X"}))
    assert "not enough data" in a.thesis.lower()


def test_thesis_flags_momentum_ahead_of_quality():
    hot_but_weak = {
        "Ticker": "HOT", "Price": "10.00",
        "P/E": "200.00", "PEG": "8.00", "Profit Margin": "-20.00%",
        "ROE": "-10.00%", "EPS next 5Y": "-5.00%", "Recom": "3.50",
        "RSI (14)": "85.00", "SMA200": "60.00%", "Perf Year": "300.00%",
        "Debt/Eq": "5.00",
    }
    a = analyze(make_data(hot_but_weak))
    assert "ahead of the fundamentals" in a.thesis


# ---------------------------------------------------------------------------
# 52-week range position & dimension transparency
# ---------------------------------------------------------------------------

def test_range_position_between_0_and_100():
    a = analyze(make_data(fixtures.AAPL_FUNDAMENTALS))
    # AAPL fixture is 2.1% off its high and 38.5% above its low -> near the top.
    assert a.range_position is not None
    assert 70 <= a.range_position <= 100


def test_range_position_missing_when_no_data():
    a = analyze(make_data({"Ticker": "X", "Price": "10.00"}))
    assert a.range_position is None


def test_dimensions_expose_raw_values():
    a = analyze(make_data(fixtures.AAPL_FUNDAMENTALS))
    val = a.dimension("Valuation")
    assert val.raw.get("P/E") == "31.50"
    analyst = a.dimension("Analyst")
    assert "Target upside" in analyst.raw  # derived value still surfaced


def test_sector_surfaced():
    a = analyze(make_data(fixtures.AAPL_FUNDAMENTALS))
    assert a.sector == "Technology"


# ---------------------------------------------------------------------------
# New signals
# ---------------------------------------------------------------------------

def test_uptrend_intact_signal_when_above_both_smas():
    a = analyze(make_data(fixtures.AAPL_FUNDAMENTALS))
    texts = " ".join(s.text for s in a.signals)
    assert "50 & 200-day" in texts


def test_deep_drawdown_signal():
    a = analyze(make_data({"Ticker": "DD", "Price": "10.00", "52W High": "-65.00%"}))
    assert any("from 52-week high" in s.text for s in a.signals)


def test_unusual_volume_signal():
    a = analyze(make_data({"Ticker": "V", "Price": "10.00", "Rel Volume": "3.10"}))
    assert any("Unusual volume" in s.text for s in a.signals)
