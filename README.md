# StockSync

A stock watchlist **"brain"** that aggregates news and financial metrics from
[Finviz](https://finviz.com) and turns them into transparent, rule-based
scores, signals and a one-line verdict — all from your terminal.

```
AAPL  —  Apple Inc.
Score: 55.6/100   [Neutral / Mixed]   195.12 (1.45%)

Dimensions
  Valuation          █████░░░░░░░░░░░░░░░  24.0
  Profitability      ███████████████████░  94.8
  Growth             █████████░░░░░░░░░░░  44.7
  Momentum           ██████████████░░░░░░  67.8
  Analyst            █████████████░░░░░░░  65.8
  Financial Health   ████░░░░░░░░░░░░░░░░  19.3

Signals
  ▲ Near 52-week high
  ▲ Above 200-day average (uptrend)
  ▲ Analyst target upside +18%
  ▲ Analyst consensus: Buy (1.9)
  • Pays a dividend (0.5%)
  ▲ Recent insider buying (2 buys)
  ▲ Positive recent news flow

News sentiment: positive (+3/-1 of 4 headlines)
```

## What it does

StockSync pulls four feeds per ticker from Finviz — the fundamentals snapshot,
recent news headlines, analyst price targets and insider transactions — and
runs them through a scoring engine (the "brain") that produces:

- **Dimension scores (0-100)** across six axes: Valuation, Profitability,
  Growth, Momentum, Analyst sentiment and Financial Health.
- A **composite score** — the availability-weighted blend of the dimensions
  that have data, so a stock missing (say) analyst coverage is still scored
  fairly on what is known.
- **Signals** — discrete bullish/bearish/neutral flags (oversold RSI, near
  52-week high, analyst upside, high short interest, insider buying, etc.).
- **News sentiment** — a lightweight lexicon read over recent headlines.
- A **verdict** — `Strong` / `Favorable` / `Neutral / Mixed` / `Cautious` /
  `Bearish`.

Scoring is deliberately **transparent and rule-based**, not a black box: every
number traces back to a documented threshold in `stocksync/brain.py`.

## Installation

```bash
pip install finviz        # the upstream data source
pip install -e .          # install StockSync (provides the `stocksync` command)
```

Requires Python 3.8+.

## Usage

```bash
# Manage your watchlist (persisted to ~/.stocksync/watchlist.json)
stocksync add AAPL --note "core holding"
stocksync add NVDA
stocksync list
stocksync remove NVDA

# Analyse a single ticker (need not be on the watchlist)
stocksync show AAPL

# Recent headlines
stocksync news TSLA -n 8

# Ranked dashboard of the whole watchlist
stocksync dashboard

# Export a mobile-friendly HTML dashboard (used by GitHub Pages; see below)
stocksync export --output public/index.html
```

Global flags:

- `--no-color` — disable ANSI colour (also auto-disabled when piping).
- `--no-cache` — bypass the local cache and fetch fresh data.

You can also run it as a module: `python -m stocksync ...`.

## Run it on your phone (GitHub Pages)

StockSync can publish a mobile-friendly dashboard to **GitHub Pages** and keep
it refreshed with **GitHub Actions** — so you just open one URL on your phone.

The included workflow (`.github/workflows/dashboard.yml`):

- reads tickers from [`watchlist.txt`](watchlist.txt),
- builds `public/index.html` with `stocksync export`,
- deploys it to GitHub Pages,
- and re-runs on every push to `watchlist.txt`, on a weekday schedule, and on
  demand from the Actions tab.

**One-time setup:** in the repo, go to **Settings → Pages → Build and
deployment → Source** and choose **GitHub Actions**. Then run the workflow once
(Actions tab → *Build & publish dashboard* → *Run workflow*). Your dashboard
will be at `https://<your-username>.github.io/StockSync/`.

The published page has two tabs:

- **Watchlist** — a card per ticker, plus an **Add ticker** box and a **✕
  Remove** button on each card.
- **Insights** —
  - **Recommendations off your watchlist** — candidates are drawn from
    *fundamental/analyst screens* (analyst buy-or-better, quality-value,
    profitable-growth; all liquidity- and price-filtered), then ranked and
    gated on a **momentum-excluded quality score** so a stock can't qualify
    just because it had a big up-day. Each rec shows its fundamental reasons
    and a quick-add button.
  - **Top 10 market news** — Finviz's general market feed, numbered and
    sentiment-coloured.
  - **Market movers & trends off your watchlist** — top gainers, top losers,
    new 52-week highs and unusual volume from Finviz's screener.
  - Plus your watchlist's own recommendations, moves and news.

The workflow rebuilds the data three times on weekdays — at market open
(~9:30 ET), midday (~1pm ET) and market close (~4pm ET) — and the open page
auto-refreshes hourly to pick up the latest build.

**Editing the watchlist from the page (optional).** Because Pages is static,
the Add/Remove buttons commit to `watchlist.txt` via the GitHub API. Tap the
**⚙** button and paste a
[fine-grained token](https://github.com/settings/personal-access-tokens/new)
scoped to this repo with **Contents: Read and write**. The token is stored only
in your browser (localStorage) — don't do this on a shared device. After an
add/remove, the workflow rebuilds and the page reloads in ~90s.

**Or just edit the file:** change `watchlist.txt` straight from the GitHub
website/app (pencil icon → edit → *Commit changes*) — no token needed. The page
rebuilds automatically. GitHub's runners can reach Finviz, so the data is live.

You can also generate the page locally:

```bash
stocksync export --watchlist-file watchlist.txt --output public/index.html
open public/index.html
```

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `STOCKSYNC_HOME` | `~/.stocksync` | Directory for the watchlist and cache. |
| `STOCKSYNC_CACHE_TTL` | `300` | Seconds a cached Finviz snapshot stays fresh. |

Fetched data is cached on disk so repeatedly viewing a watchlist does not
hammer Finviz (and works offline once warmed).

## Library API

The CLI is a thin wrapper; everything is usable as a library:

```python
from stocksync import FinvizProvider, Watchlist, analyze

provider = FinvizProvider()
data = provider.fetch("AAPL")          # StockData bundle (fundamentals, news, ...)
analysis = analyze(data)               # the brain output
print(analysis.composite, analysis.verdict)
for dim in analysis.dimensions:
    print(dim.name, dim.score)
```

`FinvizProvider` accepts the four fetch functions as constructor arguments,
which makes it trivial to test or to swap in a different data source without
touching the brain.

## How the brain scores

Each dimension is scored from the metrics Finviz actually returns:

| Dimension | Inputs (higher score when…) |
| --- | --- |
| Valuation | P/E, PEG, P/B, P/S — *lower* is better |
| Profitability | ROE, ROA, Profit Margin, Operating Margin |
| Growth | EPS next Y / next 5Y, Sales Q/Q, EPS Q/Q |
| Momentum | Perf Quarter/Year, distance above SMA50/200, RSI |
| Analyst | Recommendation (1=Strong Buy), upside to target price |
| Financial Health | Debt/Equity, Current Ratio, Quick Ratio |

Missing metrics are dropped rather than counted as zero, and the composite
re-normalises over whatever data is present.

## Architecture

```
stocksync/
  metrics.py     # parse Finviz display strings -> numbers
  config.py      # data-dir / cache paths and TTL
  providers.py   # FinvizProvider: fetch + cache + graceful degradation
  watchlist.py   # persistent ticker list with notes
  brain.py       # scoring engine: dimensions, signals, news, verdict
  report.py      # terminal rendering (colour-optional, no deps)
  webreport.py   # self-contained mobile HTML dashboard (GitHub Pages)
  cli.py         # argparse command-line interface
.github/workflows/dashboard.yml  # build + publish to GitHub Pages
watchlist.txt    # repo-committed tickers driving the published dashboard
tests/           # full pytest suite (no network required)
```

## Testing

```bash
pip install pytest
pytest
```

The test suite mocks the Finviz fetch functions, so it runs fully offline.

## Disclaimer

StockSync is an information and research aid, **not financial advice**. Data is
sourced from Finviz and may be delayed or inaccurate. Do your own research.
