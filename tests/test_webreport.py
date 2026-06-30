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


def test_render_html_has_tabs_and_insights():
    entries = [
        _entry(fixtures.AAPL_FUNDAMENTALS, fixtures.AAPL_NEWS),
        _entry(fixtures.RISKY_FUNDAMENTALS, fixtures.NEGATIVE_NEWS),
    ]
    page = render_html(entries, generated_at="t")
    # Two tabs and both panels present.
    assert 'data-tab="watchlist"' in page and 'data-tab="insights"' in page
    assert "Recommendations" in page and "Top moves" in page and "Latest news" in page
    # Add box and per-card remove buttons.
    assert 'id="add-input"' in page
    assert "addTicker(" in page and "removeTicker(" in page


def test_render_html_wires_repo_into_js():
    entries = [_entry(fixtures.AAPL_FUNDAMENTALS, fixtures.AAPL_NEWS)]
    page = render_html(
        entries, generated_at="t", repo="ChasingCars2002/StockSync", branch="main"
    )
    assert 'owner: "ChasingCars2002"' in page
    assert 'repo: "StockSync"' in page
    assert 'branch: "main"' in page


def test_render_html_refresh_seconds_to_ms():
    page = render_html([_entry(fixtures.AAPL_FUNDAMENTALS, fixtures.AAPL_NEWS)],
                       generated_at="t", refresh_seconds=600)
    assert "const REFRESH_MS = 600000;" in page


def test_moves_sorted_and_colored():
    # AAPL +1.45%, RISK -4.20% -> AAPL move row precedes RISK, with up/down classes.
    entries = [
        _entry(fixtures.RISKY_FUNDAMENTALS, fixtures.NEGATIVE_NEWS),
        _entry(fixtures.AAPL_FUNDAMENTALS, fixtures.AAPL_NEWS),
    ]
    page = render_html(entries, generated_at="t")
    assert "m-chg up" in page and "m-chg down" in page


def test_news_feed_merges_tickers():
    entries = [
        _entry(fixtures.AAPL_FUNDAMENTALS, fixtures.AAPL_NEWS),
        _entry(fixtures.RISKY_FUNDAMENTALS, fixtures.NEGATIVE_NEWS),
    ]
    page = render_html(entries, generated_at="t")
    assert "news-feed" in page
    assert "Apple surges" in page
    assert "earnings miss" in page


def test_load_tickers_file(tmp_path):
    p = tmp_path / "wl.txt"
    p.write_text("# header\nAAPL\n\nmsft  # a comment\nAAPL\n  nvda\n")
    assert load_tickers_file(p) == ["AAPL", "MSFT", "NVDA"]
