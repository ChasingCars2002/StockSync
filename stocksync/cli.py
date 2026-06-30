"""Command-line interface for StockSync.

Usage examples::

    stocksync add AAPL --note "core holding"
    stocksync list
    stocksync show NVDA
    stocksync news TSLA -n 8
    stocksync dashboard

The CLI wires together the watchlist, the Finviz provider and the brain. It
is deliberately thin: all real logic lives in the library modules so it can be
reused (and tested) without going through argument parsing.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import brain, report, webreport
from .providers import FinvizProvider
from .watchlist import Watchlist, load_tickers_file


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stocksync",
        description="A stock watchlist 'brain' that aggregates news and financial metrics via Finviz.",
    )
    parser.add_argument("--no-color", action="store_true", help="disable coloured output")
    parser.add_argument(
        "--no-cache", action="store_true", help="bypass the local cache and fetch fresh data"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="add a ticker to the watchlist")
    p_add.add_argument("ticker")
    p_add.add_argument("--note", help="optional note to attach to the ticker")

    p_rm = sub.add_parser("remove", aliases=["rm"], help="remove a ticker from the watchlist")
    p_rm.add_argument("ticker")

    sub.add_parser("list", aliases=["ls"], help="list watchlist tickers")

    p_show = sub.add_parser("show", help="show a full analysis for one ticker")
    p_show.add_argument("ticker")

    p_news = sub.add_parser("news", help="show recent headlines for a ticker")
    p_news.add_argument("ticker")
    p_news.add_argument("-n", "--limit", type=int, default=5, help="number of headlines")

    sub.add_parser(
        "dashboard", aliases=["dash"], help="ranked dashboard of every watchlist ticker"
    )

    p_export = sub.add_parser(
        "export", help="render a mobile-friendly HTML dashboard (e.g. for GitHub Pages)"
    )
    p_export.add_argument(
        "--output", "-o", default="public/index.html", help="output HTML path"
    )
    p_export.add_argument(
        "--watchlist-file",
        help="plain-text file of tickers (one per line); defaults to the saved watchlist",
    )
    p_export.add_argument(
        "--tickers", nargs="+", help="explicit tickers to include (overrides watchlist)"
    )
    p_export.add_argument("--title", default="StockSync", help="page title")

    return parser


def _provider(args: argparse.Namespace) -> FinvizProvider:
    return FinvizProvider()


def _color(args: argparse.Namespace) -> bool:
    # Honour --no-color and also auto-disable when output is not a TTY.
    return not args.no_color and sys.stdout.isatty()


def _cmd_add(args, wl: Watchlist) -> int:
    added = wl.add(args.ticker, note=args.note)
    symbol = args.ticker.upper().strip()
    if added:
        print(f"Added {symbol} to watchlist ({len(wl)} total).")
    else:
        print(f"{symbol} is already on the watchlist" + (" (note updated)." if args.note else "."))
    return 0


def _cmd_remove(args, wl: Watchlist) -> int:
    if wl.remove(args.ticker):
        print(f"Removed {args.ticker.upper().strip()} ({len(wl)} remaining).")
        return 0
    print(f"{args.ticker.upper().strip()} is not on the watchlist.")
    return 1


def _cmd_list(args, wl: Watchlist) -> int:
    if not len(wl):
        print("Watchlist is empty. Add a ticker with: stocksync add <TICKER>")
        return 0
    for ticker in wl:
        note = wl.note(ticker)
        suffix = f"  — {note}" if note else ""
        print(f"  {ticker}{suffix}")
    return 0


def _cmd_show(args, wl: Watchlist, provider: FinvizProvider, color: bool) -> int:
    data = provider.fetch(args.ticker, use_cache=not args.no_cache)
    if not data.ok:
        print(f"Could not load data for {data.ticker}.", file=sys.stderr)
        for err in data.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    analysis = brain.analyze(data)
    print(report.render_analysis(analysis, color=color, note=wl.note(args.ticker)))
    return 0


def _cmd_news(args, provider: FinvizProvider, color: bool) -> int:
    data = provider.fetch(args.ticker, use_cache=not args.no_cache)
    print(f"{data.ticker} — latest headlines")
    print(report.render_headlines(data.news, limit=args.limit, color=color))
    return 0


def _cmd_dashboard(args, wl: Watchlist, provider: FinvizProvider, color: bool) -> int:
    if not len(wl):
        print("Watchlist is empty. Add a ticker with: stocksync add <TICKER>")
        return 0
    analyses = []
    for ticker in wl:
        data = provider.fetch(ticker, use_cache=not args.no_cache)
        if data.ok:
            analyses.append(brain.analyze(data))
        else:
            print(f"  (skipped {ticker}: no data)", file=sys.stderr)
    if not analyses:
        print("No data could be loaded for any watchlist ticker.", file=sys.stderr)
        return 1
    print(report.render_dashboard(analyses, color=color))
    return 0


def _resolve_export_tickers(args, wl: Watchlist) -> List[str]:
    if args.tickers:
        return [t.upper().strip() for t in args.tickers]
    if args.watchlist_file:
        return load_tickers_file(args.watchlist_file)
    return wl.tickers


def _cmd_export(args, wl: Watchlist, provider: FinvizProvider) -> int:
    import os
    from datetime import datetime, timezone

    tickers = _resolve_export_tickers(args, wl)
    if not tickers:
        print("No tickers to export. Provide --tickers, --watchlist-file, or add some.", file=sys.stderr)
        return 1

    entries = []
    skipped = []
    for ticker in tickers:
        data = provider.fetch(ticker, use_cache=not args.no_cache)
        if data.ok:
            entries.append((brain.analyze(data), data))
        else:
            skipped.append(ticker)
            print(f"  (skipped {ticker}: no data)", file=sys.stderr)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = webreport.render_html(
        entries, generated_at=generated_at, title=args.title, skipped=skipped
    )

    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"Wrote {args.output} ({len(entries)} tickers, {len(skipped)} skipped).")
    return 0 if entries else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    color = _color(args)
    wl = Watchlist()

    if args.command == "add":
        return _cmd_add(args, wl)
    if args.command in ("remove", "rm"):
        return _cmd_remove(args, wl)
    if args.command in ("list", "ls"):
        return _cmd_list(args, wl)

    # Commands below need network/data.
    provider = _provider(args)
    if args.command == "show":
        return _cmd_show(args, wl, provider, color)
    if args.command == "news":
        return _cmd_news(args, provider, color)
    if args.command in ("dashboard", "dash"):
        return _cmd_dashboard(args, wl, provider, color)
    if args.command == "export":
        return _cmd_export(args, wl, provider)

    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
