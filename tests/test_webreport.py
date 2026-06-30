from stocksync.brain import analyze
from stocksync.providers import StockData
from stocksync.watchlist import load_tickers_file
from stocksync.webreport import render_html
from tests import fixtures


def _entry(fundamentals, news):
    data = StockData(
        ticker=fundamentals["Ticker"],
        fundamentals=dict(fundamentals),
        news=list(news),
        insider=list(fixtures.AAPL_INSIDER),
    )
    return analyze(data), data


def test_render_html_contains_tickers_and_scores():
    entries = [
        _entry(fixtures.AAPL_FUNDAMENTALS, fixtures.AAPL_NEWS),
        _entry(fixtures.RISKY_FUNDAMENTALS, fixtures.NEGATIVE_NEWS),
    ]
    page = render_html(entries, generated_at="2026-06-30 14:00 UTC")
    assert "<!DOCTYPE html>" in page
    assert "AAPL" in page and "RISK" in page
    assert "Apple Inc." in page
    assert "viewport" in page  # mobile meta tag
    assert "2026-06-30 14:00 UTC" in page


def test_render_html_sorts_by_score_desc():
    entries = [
        _entry(fixtures.RISKY_FUNDAMENTALS, fixtures.NEGATIVE_NEWS),
        _entry(fixtures.AAPL_FUNDAMENTALS, fixtures.AAPL_NEWS),
    ]
    page = render_html(entries, generated_at="t")
    # The stronger ticker's card should appear before the weaker one.
    assert page.index("AAPL") < page.index("RISK")


def test_render_html_escapes_content():
    data = StockData(
        ticker="EVIL",
        fundamentals={"Ticker": "EVIL", "Company": "<script>x</script>", "Price": "1"},
        news=[],
    )
    page = render_html([(analyze(data), data)], generated_at="t")
    assert "<script>x</script>" not in page
    assert "&lt;script&gt;" in page


def test_render_html_reports_skipped():
    page = render_html([], generated_at="t", skipped=["ZZZZ", "BADX"])
    assert "ZZZZ" in page and "BADX" in page


def test_render_html_empty():
    page = render_html([], generated_at="t")
    assert "No tickers" in page


def test_load_tickers_file(tmp_path):
    p = tmp_path / "wl.txt"
    p.write_text("# header\nAAPL\n\nmsft  # a comment\nAAPL\n  nvda\n")
    assert load_tickers_file(p) == ["AAPL", "MSFT", "NVDA"]
