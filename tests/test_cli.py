"""End-to-end CLI tests with the Finviz provider monkeypatched out."""

import stocksync.cli as cli
from stocksync.providers import FinvizProvider
from tests import fixtures


def _fake_provider(cache_file):
    return FinvizProvider(
        get_stock=lambda t: dict(fixtures.AAPL_FUNDAMENTALS),
        get_news=lambda t: list(fixtures.AAPL_NEWS),
        get_analyst_price_targets=lambda t: list(fixtures.AAPL_RATINGS),
        get_insider=lambda t: list(fixtures.AAPL_INSIDER),
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
