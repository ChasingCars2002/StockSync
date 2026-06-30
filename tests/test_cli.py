"""End-to-end CLI tests with the Finviz provider monkeypatched out."""

import stocksync.cli as cli
from stocksync.providers import FinvizProvider
from tests import fixtures


# A genuinely high-quality profile (cheap, profitable, growing, low debt,
# analyst Buy) so it clears the recommendation quality gate.
_STRONG = {
    "Company": "Candidate Co", "Price": "50.00", "Change": "2.00%",
    "P/E": "12.00", "PEG": "0.80", "P/B": "2.00", "P/S": "2.00",
    "ROE": "28.00%", "ROA": "18.00%", "Profit Margin": "22.00%", "Oper. Margin": "25.00%",
    "EPS next Y": "20.00%", "EPS next 5Y": "22.00%", "Sales Q/Q": "18.00%",
    "Recom": "1.70", "Target Price": "65.00",
    "Debt/Eq": "0.20", "Current Ratio": "2.50", "Quick Ratio": "2.00",
    "RSI (14)": "55.00", "SMA200": "5.00%",
}


def _fake_provider(cache_file):
    def stock(t):
        if t == "CAND":
            return dict(_STRONG, Ticker="CAND")
        return dict(fixtures.AAPL_FUNDAMENTALS, Ticker=t)

    return FinvizProvider(
        get_stock=stock,
        get_news=lambda t: list(fixtures.AAPL_NEWS),
        get_analyst_price_targets=lambda t: list(fixtures.AAPL_RATINGS),
        get_insider=lambda t: list(fixtures.AAPL_INSIDER),
        # Inject screener/news so export tests stay fully offline.
        get_screener=lambda sig, lim: [
            {"Ticker": "GME", "Company": "GameStop", "Price": "30", "Change": "9%"}
        ],
        get_filter_screener=lambda filt, order, lim: [
            {"Ticker": "CAND", "Company": "Candidate Co", "Price": "50", "Change": "2%"}
        ],
        get_all_news=lambda: [("09:00AM", "Markets steady", "https://n/1", "Reuters")],
        cache_path=cache_file,
    )


def setup_env(monkeypatch, tmp_path):
    """Point watchlist + provider at temp locations."""
    monkeypatch.setenv("STOCKSYNC_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "_provider", lambda args: _fake_provider(tmp_path / "cache.json"))


def test_add_list_remove_flow(monkeypatch, tmp_path, capsys):
    setup_env(monkeypatch, tmp_path)

    assert cli.main(["add", "aapl", "--note", "core"]) == 0
    assert "Added AAPL" in capsys.readouterr().out

    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "AAPL" in out and "core" in out

    assert cli.main(["remove", "AAPL"]) == 0
    assert "Removed AAPL" in capsys.readouterr().out

    assert cli.main(["list"]) == 0
    assert "empty" in capsys.readouterr().out


def test_remove_missing_returns_error(monkeypatch, tmp_path, capsys):
    setup_env(monkeypatch, tmp_path)
    assert cli.main(["remove", "ZZZZ"]) == 1


def test_show(monkeypatch, tmp_path, capsys):
    setup_env(monkeypatch, tmp_path)
    assert cli.main(["--no-color", "show", "AAPL"]) == 0
    out = capsys.readouterr().out
    assert "Apple Inc." in out
    assert "Score:" in out
    assert "Dimensions" in out


def test_news(monkeypatch, tmp_path, capsys):
    setup_env(monkeypatch, tmp_path)
    assert cli.main(["--no-color", "news", "AAPL", "-n", "3"]) == 0
    out = capsys.readouterr().out
    assert "headlines" in out.lower()
    assert "Apple surges" in out


def test_dashboard(monkeypatch, tmp_path, capsys):
    setup_env(monkeypatch, tmp_path)
    cli.main(["add", "AAPL"])
    capsys.readouterr()
    assert cli.main(["--no-color", "dashboard"]) == 0
    out = capsys.readouterr().out
    assert "TICKER" in out
    assert "AAPL" in out


def test_dashboard_empty_watchlist(monkeypatch, tmp_path, capsys):
    setup_env(monkeypatch, tmp_path)
    assert cli.main(["dashboard"]) == 0
    assert "empty" in capsys.readouterr().out


def test_export_writes_html(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    out = tmp_path / "site" / "index.html"
    rc = cli.main(["export", "--tickers", "AAPL", "MSFT", "--output", str(out)])
    assert rc == 0
    assert out.exists()
    page = out.read_text()
    assert "<!DOCTYPE html>" in page
    assert "AAPL" in page and "MSFT" in page


def test_export_from_watchlist_file(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    wl_file = tmp_path / "wl.txt"
    wl_file.write_text("AAPL\n# note\nMSFT\n")
    out = tmp_path / "index.html"
    rc = cli.main(["export", "--watchlist-file", str(wl_file), "--output", str(out)])
    assert rc == 0
    assert "AAPL" in out.read_text()


def test_export_no_tickers_errors(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    rc = cli.main(["export", "--output", str(tmp_path / "i.html")])
    assert rc == 1


def test_export_builds_insights_sections(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    out = tmp_path / "index.html"
    rc = cli.main(["export", "--tickers", "AAPL", "--output", str(out)])
    assert rc == 0
    page = out.read_text()
    # Off-watchlist recommendation candidate (from the filter screen) and the
    # market-news + movers sections are all present.
    assert "CAND" in page
    assert "Top 10 market news" in page and "Markets steady" in page
    assert "Market movers" in page and "GME" in page
