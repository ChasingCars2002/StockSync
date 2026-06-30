"""The "brain": turns raw Finviz data into scores, signals and a verdict.

Given a :class:`~stocksync.providers.StockData` bundle, :func:`analyze`
produces an :class:`Analysis` containing:

* **dimension scores** (0-100) across valuation, profitability, growth,
  momentum, analyst sentiment and financial health — each computed only from
  the metrics that are actually present;
* a **composite score**, the availability-weighted blend of those dimensions;
* a list of human-readable **signals** (bullish / bearish / neutral flags);
* a lightweight **news-sentiment** read derived from recent headlines;
* a one-line **verdict**.

Scoring is deliberately transparent and rule-based rather than a black box:
every number traces back to a documented threshold, so a user can sanity-check
why a stock scored the way it did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .metrics import clamp, parse_number
from .providers import StockData

# ---------------------------------------------------------------------------
# News sentiment lexicon
# ---------------------------------------------------------------------------

_POSITIVE_WORDS = {
    "beat", "beats", "surge", "surges", "soar", "soars", "upgrade", "upgraded",
    "record", "growth", "gain", "gains", "rally", "rallies", "jump", "jumps",
    "profit", "strong", "bullish", "outperform", "raise", "raised", "top",
    "tops", "win", "wins", "approval", "approved", "breakthrough", "expand",
    "expands", "partnership", "acquire", "acquires", "buyback", "dividend",
    "rise", "rises", "boost", "boosts", "high", "highs", "optimistic", "upbeat",
}

_NEGATIVE_WORDS = {
    "miss", "misses", "plunge", "plunges", "drop", "drops", "downgrade",
    "downgraded", "fall", "falls", "loss", "losses", "lawsuit", "probe",
    "recall", "cut", "cuts", "weak", "bearish", "underperform", "slump",
    "slumps", "decline", "declines", "warning", "warn", "warns", "sink",
    "sinks", "layoff", "layoffs", "fraud", "investigation", "bankruptcy",
    "halt", "halts", "slash", "slashes", "selloff", "sell-off", "crash",
    "crashes", "fear", "fears", "plummet", "plummets", "tumble", "tumbles",
    "low", "lows", "concern", "concerns", "risk", "risks",
}


@dataclass
class DimensionScore:
    """A 0-100 score for one analytical dimension plus its contributing parts."""

    name: str
    score: Optional[float]  # None when no underlying metric was available
    components: Dict[str, float] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.score is not None


@dataclass
class Signal:
    """A discrete, human-readable observation about the stock."""

    text: str
    sentiment: str  # "bullish" | "bearish" | "neutral"


@dataclass
class NewsSentiment:
    score: float          # 0-100, 50 == neutral
    positive: int
    negative: int
    headlines_scored: int

    @property
    def label(self) -> str:
        if self.headlines_scored == 0:
            return "no recent news"
        if self.score >= 60:
            return "positive"
        if self.score <= 40:
            return "negative"
        return "mixed"


@dataclass
class Analysis:
    """The full brain output for one ticker."""

    ticker: str
    company: str
    composite: Optional[float]
    dimensions: List[DimensionScore]
    signals: List[Signal]
    news: NewsSentiment
    verdict: str
    # A few raw display fields surfaced for convenient rendering.
    price: Optional[str] = None
    change: Optional[str] = None
    data_errors: List[str] = field(default_factory=list)

    def dimension(self, name: str) -> Optional[DimensionScore]:
        for dim in self.dimensions:
            if dim.name == name:
                return dim
        return None


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_linear(value: float, low: float, high: float, invert: bool = False) -> float:
    """Map *value* in ``[low, high]`` to ``[0, 100]`` (clamped).

    With ``invert=True`` a *lower* value yields a *higher* score, which is
    what valuation / leverage metrics want (cheaper / less debt is better).
    """
    if high == low:
        return 50.0
    pct = (value - low) / (high - low)
    if invert:
        pct = 1.0 - pct
    return clamp(pct * 100.0)


def _mean(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _f(fundamentals: Dict[str, str], key: str) -> Optional[float]:
    """Parse fundamental *key* into a float, or ``None`` if absent/unparseable."""
    return parse_number(fundamentals.get(key))


# ---------------------------------------------------------------------------
# Per-dimension scoring
# ---------------------------------------------------------------------------

def _score_valuation(f: Dict[str, str]) -> DimensionScore:
    parts: Dict[str, float] = {}
    pe = _f(f, "P/E")
    if pe is not None and pe > 0:
        parts["P/E"] = _score_linear(pe, 5, 40, invert=True)
    peg = _f(f, "PEG")
    if peg is not None and peg > 0:
        parts["PEG"] = _score_linear(peg, 0.5, 3.0, invert=True)
    pb = _f(f, "P/B")
    if pb is not None and pb > 0:
        parts["P/B"] = _score_linear(pb, 0.5, 8.0, invert=True)
    ps = _f(f, "P/S")
    if ps is not None and ps > 0:
        parts["P/S"] = _score_linear(ps, 0.5, 15.0, invert=True)
    return DimensionScore("Valuation", _mean(list(parts.values())), parts)


def _score_profitability(f: Dict[str, str]) -> DimensionScore:
    parts: Dict[str, float] = {}
    for key in ("ROE", "ROA", "Profit Margin", "Oper. Margin"):
        val = _f(f, key)
        if val is not None:
            parts[key] = _score_linear(val, 0, 30)
    return DimensionScore("Profitability", _mean(list(parts.values())), parts)


def _score_growth(f: Dict[str, str]) -> DimensionScore:
    parts: Dict[str, float] = {}
    for key in ("EPS next Y", "EPS next 5Y", "Sales Q/Q", "EPS Q/Q", "Sales past 5Y"):
        val = _f(f, key)
        if val is not None:
            parts[key] = _score_linear(val, -10, 30)
    return DimensionScore("Growth", _mean(list(parts.values())), parts)


def _score_momentum(f: Dict[str, str]) -> DimensionScore:
    parts: Dict[str, float] = {}
    for key in ("Perf Quarter", "Perf Half Y", "Perf Year"):
        val = _f(f, key)
        if val is not None:
            parts[key] = _score_linear(val, -30, 50)
    # Finviz SMA fields are "% above/below the moving average"; positive == above.
    for key in ("SMA50", "SMA200"):
        val = _f(f, key)
        if val is not None:
            parts[key] = _score_linear(val, -20, 20)
    rsi = _f(f, "RSI (14)")
    if rsi is not None:
        parts["RSI (14)"] = _score_linear(rsi, 30, 70)
    return DimensionScore("Momentum", _mean(list(parts.values())), parts)


def _analyst_upside(f: Dict[str, str]) -> Optional[float]:
    """Percent upside from current price to the mean analyst target price."""
    price = _f(f, "Price")
    target = _f(f, "Target Price")
    if price and target and price > 0:
        return (target - price) / price * 100.0
    return None


def _score_analyst(f: Dict[str, str]) -> DimensionScore:
    parts: Dict[str, float] = {}
    recom = _f(f, "Recom")
    if recom is not None:
        # Finviz Recom: 1 == Strong Buy ... 5 == Strong Sell.
        parts["Recom"] = clamp((5.0 - recom) / 4.0 * 100.0)
    upside = _analyst_upside(f)
    if upside is not None:
        parts["Target upside"] = _score_linear(upside, -20, 50)
    return DimensionScore("Analyst", _mean(list(parts.values())), parts)


def _score_health(f: Dict[str, str]) -> DimensionScore:
    parts: Dict[str, float] = {}
    deq = _f(f, "Debt/Eq")
    if deq is not None and deq >= 0:
        parts["Debt/Eq"] = _score_linear(deq, 0, 2.0, invert=True)
    cur = _f(f, "Current Ratio")
    if cur is not None:
        parts["Current Ratio"] = _score_linear(cur, 0.5, 2.5)
    quick = _f(f, "Quick Ratio")
    if quick is not None:
        parts["Quick Ratio"] = _score_linear(quick, 0.5, 2.0)
    return DimensionScore("Financial Health", _mean(list(parts.values())), parts)


# Composite weights. Dimensions with no data are dropped and the remaining
# weights re-normalised, so a stock missing (say) analyst coverage is still
# scored fairly on what is known.
_WEIGHTS = {
    "Valuation": 0.15,
    "Profitability": 0.20,
    "Growth": 0.15,
    "Momentum": 0.20,
    "Analyst": 0.15,
    "Financial Health": 0.15,
}


def _composite(dimensions: List[DimensionScore]) -> Optional[float]:
    num = 0.0
    den = 0.0
    for dim in dimensions:
        if dim.available:
            weight = _WEIGHTS.get(dim.name, 0.0)
            num += dim.score * weight
            den += weight
    if den == 0:
        return None
    return num / den


# ---------------------------------------------------------------------------
# News sentiment
# ---------------------------------------------------------------------------

def classify_headline(headline: str) -> str:
    """Classify a single headline as ``"positive"``, ``"negative"`` or ``"neutral"``."""
    tokens = {tok.strip(".,:;!?\"'()[]").lower() for tok in str(headline).split()}
    pos = len(tokens & _POSITIVE_WORDS)
    neg = len(tokens & _NEGATIVE_WORDS)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def score_news(news: List) -> NewsSentiment:
    """Score a list of Finviz news tuples by simple headline lexicon matching."""
    positive = 0
    negative = 0
    scored = 0
    for item in news:
        # Finviz news tuples are (timestamp, headline, url, source).
        headline = item[1] if len(item) > 1 else ""
        tokens = {
            tok.strip(".,:;!?\"'()[]").lower() for tok in str(headline).split()
        }
        pos = len(tokens & _POSITIVE_WORDS)
        neg = len(tokens & _NEGATIVE_WORDS)
        if pos or neg:
            scored += 1
            if pos > neg:
                positive += 1
            elif neg > pos:
                negative += 1
    if scored == 0:
        return NewsSentiment(50.0, 0, 0, 0)
    net = (positive - negative) / scored  # in [-1, 1]
    return NewsSentiment(clamp(50.0 + net * 50.0), positive, negative, scored)


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def _signals(data: StockData, news: NewsSentiment) -> List[Signal]:
    f = data.fundamentals
    signals: List[Signal] = []

    rsi = _f(f, "RSI (14)")
    if rsi is not None:
        if rsi <= 30:
            signals.append(Signal(f"Oversold (RSI {rsi:.0f})", "bullish"))
        elif rsi >= 70:
            signals.append(Signal(f"Overbought (RSI {rsi:.0f})", "bearish"))

    high = _f(f, "52W High")  # % distance from the 52-week high (<= 0)
    if high is not None and high >= -3:
        signals.append(Signal("Near 52-week high", "bullish"))
    low = _f(f, "52W Low")    # % distance from the 52-week low (>= 0)
    if low is not None and 0 <= low <= 5:
        signals.append(Signal("Near 52-week low", "bearish"))

    sma200 = _f(f, "SMA200")
    if sma200 is not None:
        if sma200 > 0:
            signals.append(Signal("Above 200-day average (uptrend)", "bullish"))
        else:
            signals.append(Signal("Below 200-day average (downtrend)", "bearish"))

    upside = _analyst_upside(f)
    if upside is not None:
        if upside >= 15:
            signals.append(Signal(f"Analyst target upside +{upside:.0f}%", "bullish"))
        elif upside <= -10:
            signals.append(Signal(f"Trading above analyst target ({upside:.0f}%)", "bearish"))

    recom = _f(f, "Recom")
    if recom is not None:
        if recom <= 2.0:
            signals.append(Signal(f"Analyst consensus: Buy ({recom:.1f})", "bullish"))
        elif recom >= 4.0:
            signals.append(Signal(f"Analyst consensus: Sell ({recom:.1f})", "bearish"))

    peg = _f(f, "PEG")
    if peg is not None and 0 < peg < 1:
        signals.append(Signal(f"Cheap relative to growth (PEG {peg:.2f})", "bullish"))

    short = _f(f, "Short Float")
    if short is not None and short >= 10:
        signals.append(Signal(f"High short interest ({short:.0f}%)", "bearish"))

    div = _f(f, "Dividend %")
    if div is not None and div > 0:
        signals.append(Signal(f"Pays a dividend ({div:.1f}%)", "neutral"))

    # Insider activity: net of buy vs sell transactions Finviz reports.
    buys = sum(1 for t in data.insider if "buy" in str(t.get("Transaction", "")).lower())
    sells = sum(1 for t in data.insider if "sale" in str(t.get("Transaction", "")).lower())
    if buys > sells and buys:
        signals.append(Signal(f"Recent insider buying ({buys} buys)", "bullish"))
    elif sells > buys and sells:
        signals.append(Signal(f"Recent insider selling ({sells} sales)", "bearish"))

    if news.headlines_scored:
        if news.label == "positive":
            signals.append(Signal("Positive recent news flow", "bullish"))
        elif news.label == "negative":
            signals.append(Signal("Negative recent news flow", "bearish"))

    return signals


def _verdict(composite: Optional[float]) -> str:
    if composite is None:
        return "Insufficient data"
    if composite >= 70:
        return "Strong"
    if composite >= 57:
        return "Favorable"
    if composite >= 43:
        return "Neutral / Mixed"
    if composite >= 30:
        return "Cautious"
    return "Bearish"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(data: StockData) -> Analysis:
    """Run the full analysis pipeline over a :class:`StockData` bundle."""
    f = data.fundamentals
    dimensions = [
        _score_valuation(f),
        _score_profitability(f),
        _score_growth(f),
        _score_momentum(f),
        _score_analyst(f),
        _score_health(f),
    ]
    composite = _composite(dimensions)
    news = score_news(data.news)
    signals = _signals(data, news)
    return Analysis(
        ticker=data.ticker,
        company=data.company,
        composite=composite,
        dimensions=dimensions,
        signals=signals,
        news=news,
        verdict=_verdict(composite),
        price=f.get("Price"),
        change=f.get("Change"),
        data_errors=list(data.errors),
    )
