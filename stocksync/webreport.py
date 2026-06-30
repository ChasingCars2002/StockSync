"""Mobile-first HTML rendering of a watchlist dashboard.

Produces a single self-contained HTML document (inline CSS, no external
assets) so it can be published as a static page — e.g. to GitHub Pages — and
opened comfortably on a phone.

The page is intentionally static: all the analysis happens at build time, so
the served file is just HTML and works offline / behind any CDN.
"""

from __future__ import annotations

import html
from typing import List, Optional, Tuple

from .brain import Analysis
from .providers import StockData

# (Analysis, StockData) pairs — the StockData is kept so headlines can be shown.
Entry = Tuple[Analysis, StockData]


def _score_class(score: Optional[float]) -> str:
    if score is None:
        return "na"
    if score >= 60:
        return "good"
    if score >= 45:
        return "mid"
    return "bad"


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _bar(name: str, score: Optional[float]) -> str:
    cls = _score_class(score)
    pct = 0 if score is None else max(0, min(100, score))
    label = "n/a" if score is None else f"{score:.0f}"
    return (
        '<div class="dim">'
        f'<span class="dim-name">{_esc(name)}</span>'
        f'<span class="track"><span class="fill {cls}" style="width:{pct:.0f}%"></span></span>'
        f'<span class="dim-val">{label}</span>'
        "</div>"
    )


def _signal_chip(text: str, sentiment: str) -> str:
    marker = {"bullish": "▲", "bearish": "▼"}.get(sentiment, "•")
    return f'<span class="chip {_esc(sentiment)}">{marker} {_esc(text)}</span>'


def _headlines(data: StockData, limit: int = 3) -> str:
    if not data.news:
        return ""
    items = []
    for row in data.news[:limit]:
        headline = row[1] if len(row) > 1 else ""
        url = row[2] if len(row) > 2 else ""
        source = row[3] if len(row) > 3 else ""
        src = f' <span class="src">({_esc(source)})</span>' if source else ""
        if url:
            items.append(
                f'<li><a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(headline)}</a>{src}</li>'
            )
        else:
            items.append(f"<li>{_esc(headline)}{src}</li>")
    return '<ul class="news">' + "".join(items) + "</ul>"


def _card(analysis: Analysis, data: StockData) -> str:
    cls = _score_class(analysis.composite)
    score_txt = "n/a" if analysis.composite is None else f"{analysis.composite:.0f}"
    company = f'<span class="company">{_esc(analysis.company)}</span>' if analysis.company else ""
    price = ""
    if analysis.price:
        chg = f" ({_esc(analysis.change)})" if analysis.change else ""
        price = f'<span class="price">{_esc(analysis.price)}{chg}</span>'

    dims = "".join(_bar(d.name, d.score) for d in analysis.dimensions)
    signals = "".join(_signal_chip(s.text, s.sentiment) for s in analysis.signals)
    signals_block = f'<div class="signals">{signals}</div>' if signals else ""

    news_sent = ""
    if analysis.news.headlines_scored:
        news_sent = (
            f'<div class="news-sent {_score_class(analysis.news.score)}">'
            f"News: {_esc(analysis.news.label)} "
            f"(+{analysis.news.positive}/-{analysis.news.negative})</div>"
        )

    return f"""
    <article class="card">
      <header class="card-head">
        <div class="title">
          <span class="ticker">{_esc(analysis.ticker)}</span>
          {company}
          {price}
        </div>
        <div class="badge {cls}">
          <span class="num">{score_txt}</span>
          <span class="verdict">{_esc(analysis.verdict)}</span>
        </div>
      </header>
      <div class="dims">{dims}</div>
      {signals_block}
      {news_sent}
      {_headlines(data)}
    </article>"""


_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 16px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #0d1117; color: #e6edf3; line-height: 1.4;
}
h1 { font-size: 1.4rem; margin: 0 0 2px; }
.sub { color: #8b949e; font-size: .8rem; margin-bottom: 18px; }
.card {
  background: #161b22; border: 1px solid #30363d; border-radius: 12px;
  padding: 14px; margin-bottom: 14px;
}
.card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.title { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.ticker { font-size: 1.25rem; font-weight: 700; }
.company { color: #8b949e; font-size: .82rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.price { color: #c9d1d9; font-size: .8rem; }
.badge {
  text-align: center; border-radius: 10px; padding: 6px 12px; min-width: 86px; flex-shrink: 0;
}
.badge .num { display: block; font-size: 1.5rem; font-weight: 800; line-height: 1; }
.badge .verdict { font-size: .66rem; text-transform: uppercase; letter-spacing: .04em; }
.good { background: rgba(63,185,80,.16); color: #3fb950; }
.mid  { background: rgba(210,153,34,.16); color: #d29922; }
.bad  { background: rgba(248,81,73,.16);  color: #f85149; }
.na   { background: rgba(139,148,158,.16); color: #8b949e; }
.dims { margin: 12px 0 4px; }
.dim { display: flex; align-items: center; gap: 8px; margin: 5px 0; font-size: .78rem; }
.dim-name { flex: 0 0 116px; color: #8b949e; }
.track { flex: 1; height: 8px; background: #21262d; border-radius: 5px; overflow: hidden; }
.fill { display: block; height: 100%; border-radius: 5px; }
.fill.good { background: #3fb950; } .fill.mid { background: #d29922; }
.fill.bad { background: #f85149; } .fill.na { background: #30363d; }
.dim-val { flex: 0 0 28px; text-align: right; color: #c9d1d9; }
.signals { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 4px; }
.chip { font-size: .72rem; padding: 3px 8px; border-radius: 999px; background: #21262d; }
.chip.bullish { color: #3fb950; } .chip.bearish { color: #f85149; } .chip.neutral { color: #d29922; }
.news-sent { font-size: .76rem; margin: 8px 0 0; }
.news { margin: 8px 0 0; padding-left: 18px; font-size: .78rem; }
.news li { margin: 3px 0; }
.news a { color: #58a6ff; text-decoration: none; }
.src { color: #8b949e; }
footer { color: #8b949e; font-size: .72rem; text-align: center; margin-top: 18px; }
"""


def render_html(
    entries: List[Entry],
    *,
    generated_at: str,
    title: str = "StockSync",
    skipped: Optional[List[str]] = None,
) -> str:
    """Render a full HTML dashboard document.

    *entries* are ``(Analysis, StockData)`` pairs; they are sorted by composite
    score (highest first). *generated_at* is a display string for the build
    time. *skipped* lists tickers whose data could not be loaded.
    """
    ranked = sorted(
        entries,
        key=lambda e: (e[0].composite if e[0].composite is not None else -1),
        reverse=True,
    )
    cards = "".join(_card(a, d) for a, d in ranked)
    if not cards:
        cards = '<p class="sub">No tickers to display. Add some to your watchlist.</p>'

    skipped_note = ""
    if skipped:
        skipped_note = (
            f'<p class="sub">Data unavailable for: {_esc(", ".join(skipped))}</p>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0d1117">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{_esc(title)}</h1>
<p class="sub">Watchlist brain · {_esc(len(ranked))} tickers · updated {_esc(generated_at)}</p>
{skipped_note}
{cards}
<footer>Generated by StockSync from Finviz data. Informational only — not financial advice.</footer>
</body>
</html>"""
