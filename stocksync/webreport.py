"""Mobile-first HTML dashboard with a Watchlist tab and an Insights tab.

Produces a single self-contained HTML document (inline CSS + JS, no external
assets) suitable for publishing to GitHub Pages and opening on a phone.

Two tabs are rendered, both from build-time data:

* **Watchlist** — one card per ticker (score, dimension bars, signals, news
  sentiment, headlines) plus an "add ticker" box and a remove button on each
  card. Because Pages is static, add/remove operate by committing to the
  repo's ``watchlist.txt`` through the GitHub API using a personal access
  token the user supplies once (stored in their browser's localStorage).
* **Insights** — aggregated across the whole watchlist: top moves by percent
  change, recommendation buckets derived from the brain's scores/signals, and
  a merged, sentiment-coloured news feed (newest first).

The open page also auto-reloads on an interval so it keeps up with scheduled
rebuilds.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import List, Optional, Tuple

from .brain import Analysis, classify_headline
from .metrics import parse_number
from .providers import StockData

# (Analysis, StockData) pairs — StockData is kept so headlines can be shown.
Entry = Tuple[Analysis, StockData]


# ---------------------------------------------------------------------------
# Small rendering helpers
# ---------------------------------------------------------------------------

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

    tkr = _esc(analysis.ticker)
    return f"""
    <article class="card">
      <header class="card-head">
        <div class="title">
          <span class="ticker">{tkr}</span>
          {company}
          {price}
        </div>
        <div class="head-right">
          <div class="badge {cls}">
            <span class="num">{score_txt}</span>
            <span class="verdict">{_esc(analysis.verdict)}</span>
          </div>
          <button class="rm" title="Remove from watchlist" onclick="removeTicker('{tkr}')">&times;</button>
        </div>
      </header>
      <div class="dims">{dims}</div>
      {signals_block}
      {news_sent}
      {_headlines(data)}
    </article>"""


# ---------------------------------------------------------------------------
# Insights tab
# ---------------------------------------------------------------------------

def _moves_section(entries: List[Entry]) -> str:
    rows = []
    for a, _ in entries:
        chg = parse_number(a.change)
        if chg is None:
            continue
        rows.append((a, chg))
    rows.sort(key=lambda r: r[1], reverse=True)
    if not rows:
        return '<p class="muted">No price-change data available.</p>'

    out = []
    for a, chg in rows:
        cls = "up" if chg > 0 else "down" if chg < 0 else "flat"
        sign = "+" if chg > 0 else ""
        out.append(
            '<div class="move-row">'
            f'<span class="m-tkr">{_esc(a.ticker)}</span>'
            f'<span class="m-price">{_esc(a.price or "-")}</span>'
            f'<span class="m-chg {cls}">{sign}{chg:.2f}%</span>'
            f'<span class="m-verdict">{_esc(a.verdict)}</span>'
            "</div>"
        )
    return '<div class="moves">' + "".join(out) + "</div>"


def _market_movers_section(movers: Optional[List[Tuple[str, List[dict]]]]) -> str:
    """Render off-watchlist screener groups (gainers, losers, new highs, ...).

    *movers* is a list of ``(group_title, rows)`` where each row is a
    normalized screener dict. Each row gets a "+" button to add that ticker to
    the watchlist.
    """
    if not movers:
        return '<p class="muted">Market movers unavailable.</p>'

    groups = []
    for title, rows in movers:
        if not rows:
            continue
        out_rows = []
        for r in rows:
            tkr = _esc(r.get("ticker", ""))
            chg = parse_number(r.get("change"))
            cls = "up" if (chg or 0) > 0 else "down" if (chg or 0) < 0 else "flat"
            chg_txt = _esc(r.get("change") or "-")
            company = _esc(r.get("company", ""))
            out_rows.append(
                '<div class="move-row">'
                f'<span class="m-tkr">{tkr}</span>'
                f'<span class="m-co">{company}</span>'
                f'<span class="m-price">{_esc(r.get("price") or "-")}</span>'
                f'<span class="m-chg {cls}">{chg_txt}</span>'
                f'<button class="add-mini" title="Add to watchlist" onclick="addTicker(\'{tkr}\')">+</button>'
                "</div>"
            )
        groups.append(
            f'<h3 class="rec-title">{_esc(title)}</h3>'
            '<div class="moves">' + "".join(out_rows) + "</div>"
        )
    if not groups:
        return '<p class="muted">No market movers right now.</p>'
    return "".join(groups)


def _market_recs_section(analyses: Optional[List[Analysis]]) -> str:
    """Render brain-scored recommendations drawn from *off-watchlist* names."""
    if analyses is None:
        return '<p class="muted">Off-watchlist recommendations unavailable.</p>'
    if not analyses:
        return '<p class="muted">No strong off-watchlist setups right now.</p>'

    # Momentum-ish signals are de-emphasised in the "why" so reasons reflect
    # the fundamental/analyst case, not just price action.
    momentum_words = ("52-week", "200-day", "Oversold", "Overbought")

    rows = []
    for a in analyses:
        rank_score = a.quality_score if a.quality_score is not None else a.composite
        cls = _score_class(rank_score)
        score = "n/a" if rank_score is None else f"{rank_score:.0f}"
        reasons = [
            s.text
            for s in a.signals
            if s.sentiment == "bullish" and not any(w in s.text for w in momentum_words)
        ]
        why = (" · ".join(reasons))[:80]
        company = _esc(a.company)[:28]
        tkr = _esc(a.ticker)
        rows.append(
            '<div class="rec-row">'
            f'<span class="rec-badge {cls}">{score}</span>'
            f'<span class="rec-tkr">{tkr}</span>'
            f'<span class="rec-why"><b>{_esc(a.verdict)}</b>'
            f'{(" · " + _esc(company)) if company else ""}'
            f'{(" · " + _esc(why)) if why else ""}</span>'
            f'<button class="add-mini" title="Add to watchlist" onclick="addTicker(\'{tkr}\')">+</button>'
            "</div>"
        )
    return '<div class="moves">' + "".join(rows) + "</div>"


def _top_news_section(items: Optional[List[dict]]) -> str:
    """Render the top general market-news stories as a numbered list."""
    if items is None:
        return '<p class="muted">Market news unavailable.</p>'
    if not items:
        return '<p class="muted">No market news right now.</p>'

    out = []
    for i, it in enumerate(items, start=1):
        headline = it.get("headline", "")
        url = it.get("url", "")
        source = it.get("source", "")
        dot = {"positive": "good", "negative": "bad"}.get(classify_headline(headline), "mid")
        title = _esc(headline)
        if url:
            title = f'<a href="{_esc(url)}" target="_blank" rel="noopener">{title}</a>'
        meta = " · ".join(p for p in (_esc(it.get("time", "")), _esc(source)) if p)
        out.append(
            '<div class="news-row">'
            f'<span class="n-rank">{i}</span>'
            f'<span class="dot {dot}"></span>'
            f'<span class="n-head">{title}</span>'
            f'<span class="n-meta">{meta}</span>'
            "</div>"
        )
    return '<div class="news-feed">' + "".join(out) + "</div>"


def _recommendations_section(entries: List[Entry]) -> str:
    analyses = [a for a, _ in entries]

    def reasons(a: Analysis, sentiment: str, limit: int = 2) -> str:
        picked = [s.text for s in a.signals if s.sentiment == sentiment][:limit]
        return " · ".join(picked)

    buckets = [
        (
            "Consider",
            "good",
            [a for a in analyses if a.composite is not None and a.composite >= 57],
            "bullish",
        ),
        (
            "Watch / Neutral",
            "mid",
            [a for a in analyses if a.composite is not None and 43 <= a.composite < 57],
            "bullish",
        ),
        (
            "Caution",
            "bad",
            [a for a in analyses if a.composite is not None and a.composite < 43],
            "bearish",
        ),
    ]

    out = []
    for title, cls, items, sentiment in buckets:
        items = sorted(
            items,
            key=lambda a: a.composite if a.composite is not None else -1,
            reverse=(cls != "bad"),
        )
        if not items:
            continue
        rows = []
        for a in items:
            why = reasons(a, sentiment) or reasons(a, "neutral")
            score = "n/a" if a.composite is None else f"{a.composite:.0f}"
            rows.append(
                '<div class="rec-row">'
                f'<span class="rec-badge {cls}">{score}</span>'
                f'<span class="rec-tkr">{_esc(a.ticker)}</span>'
                f'<span class="rec-why">{_esc(why)}</span>'
                "</div>"
            )
        out.append(
            f'<div class="rec-group"><h3 class="rec-title {cls}">{_esc(title)}</h3>'
            + "".join(rows)
            + "</div>"
        )
    if not out:
        return '<p class="muted">Not enough data for recommendations.</p>'
    return "".join(out)


def _news_key(ts: str):
    """Best-effort parse of a Finviz news timestamp into a sortable datetime."""
    for fmt in ("%b-%d-%y %I:%M%p", "%b-%d-%y", "%I:%M%p"):
        try:
            return datetime.strptime(str(ts).strip(), fmt)
        except (ValueError, TypeError):
            continue
    return None


def _news_section(entries: List[Entry], limit: int = 40) -> str:
    items = []
    for a, data in entries:
        for row in data.news:
            ts = row[0] if len(row) > 0 else ""
            headline = row[1] if len(row) > 1 else ""
            url = row[2] if len(row) > 2 else ""
            source = row[3] if len(row) > 3 else ""
            items.append(
                {
                    "ticker": a.ticker,
                    "ts": ts,
                    "dt": _news_key(ts),
                    "headline": headline,
                    "url": url,
                    "source": source,
                    "sentiment": classify_headline(headline),
                }
            )
    if not items:
        return '<p class="muted">No recent headlines.</p>'

    # Stable sort: parseable timestamps newest-first; unparseable keep order, last.
    items.sort(key=lambda x: x["dt"] or datetime.min, reverse=True)

    out = []
    for it in items[:limit]:
        dot = {"positive": "good", "negative": "bad"}.get(it["sentiment"], "mid")
        title = _esc(it["headline"])
        if it["url"]:
            title = f'<a href="{_esc(it["url"])}" target="_blank" rel="noopener">{title}</a>'
        meta = _esc(it["source"]) if it["source"] else ""
        out.append(
            '<div class="news-row">'
            f'<span class="dot {dot}"></span>'
            f'<span class="n-tkr">{_esc(it["ticker"])}</span>'
            f'<span class="n-head">{title}</span>'
            f'<span class="n-meta">{_esc(it["ts"])}{(" · " + meta) if meta else ""}</span>'
            "</div>"
        )
    return '<div class="news-feed">' + "".join(out) + "</div>"


# ---------------------------------------------------------------------------
# CSS / JS
# ---------------------------------------------------------------------------

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 14px 14px 40px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #0d1117; color: #e6edf3; line-height: 1.4;
}
.topbar { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
h1 { font-size: 1.35rem; margin: 0; }
.sub { color: #8b949e; font-size: .78rem; margin: 2px 0 12px; }
.muted { color: #8b949e; font-size: .85rem; }
.gear { background: #21262d; border: 1px solid #30363d; color: #c9d1d9;
  border-radius: 8px; padding: 6px 10px; font-size: 1rem; cursor: pointer; }
.tabs { display: flex; gap: 6px; margin: 6px 0 16px; }
.tab { flex: 1; text-align: center; padding: 9px; border-radius: 9px;
  background: #161b22; border: 1px solid #30363d; color: #8b949e;
  font-weight: 600; font-size: .9rem; cursor: pointer; }
.tab.active { background: #1f6feb22; border-color: #1f6feb; color: #58a6ff; }
.panel { display: none; }
.panel.active { display: block; }
.addbar { display: flex; gap: 8px; margin-bottom: 14px; }
.addbar input { flex: 1; background: #0d1117; border: 1px solid #30363d;
  color: #e6edf3; border-radius: 9px; padding: 10px 12px; font-size: 1rem; text-transform: uppercase; }
.btn { background: #238636; border: 0; color: #fff; border-radius: 9px;
  padding: 10px 16px; font-weight: 600; font-size: .95rem; cursor: pointer; }
.btn.secondary { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 14px; margin-bottom: 14px; }
.card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.title { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.ticker { font-size: 1.25rem; font-weight: 700; }
.company { color: #8b949e; font-size: .82rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.price { color: #c9d1d9; font-size: .8rem; }
.head-right { display: flex; align-items: flex-start; gap: 8px; flex-shrink: 0; }
.badge { text-align: center; border-radius: 10px; padding: 6px 12px; min-width: 80px; }
.badge .num { display: block; font-size: 1.5rem; font-weight: 800; line-height: 1; }
.badge .verdict { font-size: .64rem; text-transform: uppercase; letter-spacing: .04em; }
.rm { background: #21262d; border: 1px solid #30363d; color: #8b949e;
  border-radius: 8px; width: 30px; height: 30px; font-size: 1.1rem; line-height: 1; cursor: pointer; }
.rm:hover { color: #f85149; border-color: #f85149; }
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
h2.section { font-size: 1rem; margin: 18px 0 8px; color: #c9d1d9; }
.moves { background: #161b22; border: 1px solid #30363d; border-radius: 12px; overflow: hidden; }
.move-row { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-top: 1px solid #21262d; font-size: .86rem; }
.move-row:first-child { border-top: 0; }
.m-tkr { font-weight: 700; flex: 0 0 56px; }
.m-co { flex: 1; color: #8b949e; font-size: .76rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.m-price { flex: 0 0 64px; color: #c9d1d9; text-align: right; }
.m-chg { flex: 0 0 64px; font-weight: 700; text-align: right; }
.m-chg.up { color: #3fb950; } .m-chg.down { color: #f85149; } .m-chg.flat { color: #8b949e; }
.m-verdict { color: #8b949e; font-size: .78rem; margin-left: auto; }
.add-mini { flex: 0 0 28px; background: #21262d; border: 1px solid #30363d; color: #3fb950;
  border-radius: 7px; height: 26px; font-size: 1rem; line-height: 1; cursor: pointer; }
.add-mini:hover { border-color: #3fb950; }
.rec-group { margin-bottom: 14px; }
.rec-title { font-size: .85rem; margin: 0 0 6px; text-transform: uppercase; letter-spacing: .04em; }
.rec-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-top: 1px solid #21262d; font-size: .84rem; }
.rec-badge { flex: 0 0 36px; text-align: center; border-radius: 7px; padding: 3px 0; font-weight: 700; font-size: .82rem; }
.rec-tkr { font-weight: 700; flex: 0 0 56px; }
.rec-why { color: #8b949e; font-size: .78rem; }
.news-feed { background: #161b22; border: 1px solid #30363d; border-radius: 12px; overflow: hidden; }
.news-row { display: flex; align-items: baseline; gap: 8px; padding: 10px 12px; border-top: 1px solid #21262d; font-size: .82rem; }
.news-row:first-child { border-top: 0; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; align-self: center; }
.dot.good { background: #3fb950; } .dot.mid { background: #8b949e; } .dot.bad { background: #f85149; }
.n-rank { flex: 0 0 20px; color: #8b949e; font-weight: 700; text-align: right; }
.n-tkr { font-weight: 700; flex: 0 0 50px; }
.n-head { flex: 1; } .n-head a { color: #58a6ff; text-decoration: none; }
.n-meta { color: #8b949e; font-size: .7rem; flex: 0 0 auto; }
footer { color: #8b949e; font-size: .72rem; text-align: center; margin-top: 18px; }
.overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.6);
  align-items: center; justify-content: center; padding: 20px; z-index: 50; }
.overlay.show { display: flex; }
.modal { background: #161b22; border: 1px solid #30363d; border-radius: 14px; padding: 18px; max-width: 420px; width: 100%; }
.modal h2 { margin: 0 0 8px; font-size: 1.1rem; }
.modal p { font-size: .82rem; color: #8b949e; }
.modal input { width: 100%; background: #0d1117; border: 1px solid #30363d; color: #e6edf3;
  border-radius: 9px; padding: 10px; font-size: .95rem; margin: 8px 0; }
.modal .row { display: flex; gap: 8px; margin-top: 6px; }
.warn { color: #d29922; font-size: .76rem; }
.toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
  background: #21262d; border: 1px solid #30363d; color: #e6edf3; padding: 10px 16px;
  border-radius: 10px; font-size: .85rem; opacity: 0; transition: opacity .2s; z-index: 60; pointer-events: none; }
.toast.show { opacity: 1; }
"""

# JS template; __PLACEHOLDERS__ are substituted at render time.
_JS = """
const REPO = {owner: "__OWNER__", repo: "__REPO__", branch: "__BRANCH__", path: "__PATH__"};
const TOKEN_KEY = "stocksync_gh_token";
const REFRESH_MS = __REFRESH__;
let modalOpen = false;

function $(id){ return document.getElementById(id); }
function getToken(){ return localStorage.getItem(TOKEN_KEY) || ""; }

function showTab(name){
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("active", p.id === "panel-" + name));
}

function toast(msg){
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(window.__tt); window.__tt = setTimeout(() => t.classList.remove("show"), 3500);
}

function openSettings(){ modalOpen = true; $("token-input").value = getToken(); $("overlay").classList.add("show"); }
function closeSettings(){ modalOpen = false; $("overlay").classList.remove("show"); }
function saveToken(){
  const v = $("token-input").value.trim();
  if (v) localStorage.setItem(TOKEN_KEY, v); else localStorage.removeItem(TOKEN_KEY);
  closeSettings();
  toast(v ? "Token saved" : "Token cleared");
}

function authHeaders(){
  const t = getToken();
  const h = {"Accept": "application/vnd.github+json"};
  if (t) h["Authorization"] = "Bearer " + t;
  return h;
}

function parseTickers(text){
  const seen = new Set(), out = [];
  text.split(/\\r?\\n/).forEach(line => {
    const s = line.split("#")[0].trim().toUpperCase();
    if (s && !seen.has(s)) { seen.add(s); out.push(s); }
  });
  return out;
}

async function ghGetFile(){
  const url = `https://api.github.com/repos/${REPO.owner}/${REPO.repo}/contents/${REPO.path}?ref=${REPO.branch}`;
  const r = await fetch(url, {headers: authHeaders()});
  if (!r.ok) throw new Error("GitHub read failed (" + r.status + ")");
  const j = await r.json();
  const content = decodeURIComponent(escape(atob(j.content.replace(/\\n/g, ""))));
  return {content, sha: j.sha};
}

async function ghPutFile(content, sha, message){
  const url = `https://api.github.com/repos/${REPO.owner}/${REPO.repo}/contents/${REPO.path}`;
  const body = {message, content: btoa(unescape(encodeURIComponent(content))), sha, branch: REPO.branch};
  const r = await fetch(url, {method: "PUT", headers: {...authHeaders(), "Content-Type": "application/json"}, body: JSON.stringify(body)});
  if (!r.ok) { let e = ""; try { e = (await r.json()).message || ""; } catch(_){} throw new Error("GitHub write failed (" + r.status + ") " + e); }
}

function ensureSetup(){
  if (!REPO.owner || !REPO.repo) { toast("Repo not configured in this build"); return false; }
  if (!getToken()) { toast("Add a GitHub token first"); openSettings(); return false; }
  return true;
}

function rebuildNotice(){
  toast("Saved — rebuilding, page will refresh shortly");
  setTimeout(() => location.reload(), 90000);
}

async function addTicker(sym){
  sym = (sym || $("add-input").value || "").trim().toUpperCase();
  if (!sym) return;
  if (!ensureSetup()) return;
  try {
    const {content, sha} = await ghGetFile();
    if (parseTickers(content).includes(sym)) { toast(sym + " already on watchlist"); return; }
    const next = content.replace(/\\s*$/, "") + "\\n" + sym + "\\n";
    await ghPutFile(next, sha, "Add " + sym + " to watchlist");
    $("add-input").value = "";
    rebuildNotice();
  } catch (e) { toast(e.message); }
}

async function removeTicker(sym){
  sym = (sym || "").trim().toUpperCase();
  if (!sym || !ensureSetup()) return;
  try {
    const {content, sha} = await ghGetFile();
    const kept = content.split(/\\r?\\n/).filter(line => line.split("#")[0].trim().toUpperCase() !== sym);
    await ghPutFile(kept.join("\\n"), sha, "Remove " + sym + " from watchlist");
    rebuildNotice();
  } catch (e) { toast(e.message); }
}

// Auto-refresh to keep up with scheduled rebuilds, but never interrupt typing
// or an open dialog.
setInterval(() => {
  if (modalOpen) return;
  if (document.activeElement && document.activeElement.id === "add-input") return;
  location.reload();
}, REFRESH_MS);

document.addEventListener("DOMContentLoaded", () => {
  $("add-input").addEventListener("keydown", e => { if (e.key === "Enter") addTicker(); });
});
"""


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------

def render_html(
    entries: List[Entry],
    *,
    generated_at: str,
    title: str = "StockSync",
    skipped: Optional[List[str]] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
    watchlist_path: str = "watchlist.txt",
    refresh_seconds: int = 600,
    movers: Optional[List[Tuple[str, List[dict]]]] = None,
    market_recs: Optional[List[Analysis]] = None,
    market_news: Optional[List[dict]] = None,
) -> str:
    """Render the full two-tab HTML dashboard.

    *repo* is ``"owner/name"`` (used by the in-page add/remove buttons via the
    GitHub API); when omitted the buttons render but report that the repo is
    not configured.
    """
    ranked = sorted(
        entries,
        key=lambda e: (e[0].composite if e[0].composite is not None else -1),
        reverse=True,
    )
    cards = "".join(_card(a, d) for a, d in ranked)
    if not cards:
        cards = '<p class="muted">No tickers yet. Add one above.</p>'

    skipped_note = ""
    if skipped:
        skipped_note = f'<p class="sub">Data unavailable for: {_esc(", ".join(skipped))}</p>'

    owner, name = "", ""
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)

    script = (
        _JS.replace("__OWNER__", _esc(owner))
        .replace("__REPO__", _esc(name))
        .replace("__BRANCH__", _esc(branch or ""))
        .replace("__PATH__", _esc(watchlist_path))
        .replace("__REFRESH__", str(int(refresh_seconds) * 1000))
    )

    moves = _moves_section(ranked)
    recs = _recommendations_section(ranked)
    news = _news_section(ranked)
    market = _market_movers_section(movers)
    market_rec_html = _market_recs_section(market_recs)
    top_news_html = _top_news_section(market_news)

    token_link = "https://github.com/settings/personal-access-tokens/new"

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
<div class="topbar">
  <h1>{_esc(title)}</h1>
  <button class="gear" onclick="openSettings()" title="Settings">&#9881;</button>
</div>
<p class="sub">{_esc(len(ranked))} tickers · updated {_esc(generated_at)} · auto-refresh {int(refresh_seconds)//60}m</p>
{skipped_note}

<div class="tabs">
  <div class="tab active" data-tab="watchlist" onclick="showTab('watchlist')">Watchlist</div>
  <div class="tab" data-tab="insights" onclick="showTab('insights')">Insights</div>
</div>

<section id="panel-watchlist" class="panel active">
  <div class="addbar">
    <input id="add-input" placeholder="Add ticker (e.g. AAPL)" autocapitalize="characters" autocomplete="off">
    <button class="btn" onclick="addTicker()">Add</button>
  </div>
  {cards}
</section>

<section id="panel-insights" class="panel">
  <h2 class="section">Recommendations <span class="muted">(off your watchlist · fundamentals &amp; analysts, momentum excluded)</span></h2>
  {market_rec_html}
  <h2 class="section">Top 10 market news</h2>
  {top_news_html}
  <h2 class="section">Market movers &amp; trends <span class="muted">(off your watchlist)</span></h2>
  {market}
  <h2 class="section">Recommendations <span class="muted">(your watchlist)</span></h2>
  {recs}
  <h2 class="section">Watchlist moves</h2>
  {moves}
  <h2 class="section">Watchlist news</h2>
  {news}
</section>

<footer>Generated by StockSync from Finviz data. Informational only — not financial advice.</footer>

<div id="overlay" class="overlay">
  <div class="modal">
    <h2>Watchlist editing</h2>
    <p>Add/remove buttons save to <code>{_esc(watchlist_path)}</code> in your repo via the GitHub API.
       Paste a <a href="{token_link}" target="_blank" rel="noopener">fine-grained token</a>
       scoped to this repo with <b>Contents: Read and write</b>.</p>
    <input id="token-input" type="password" placeholder="github_pat_..." autocomplete="off">
    <p class="warn">Stored only in this browser (localStorage). Don't use this on a shared device.</p>
    <div class="row">
      <button class="btn" onclick="saveToken()">Save</button>
      <button class="btn secondary" onclick="closeSettings()">Cancel</button>
    </div>
  </div>
</div>
<div id="toast" class="toast"></div>

<script>{script}</script>
</body>
</html>"""
