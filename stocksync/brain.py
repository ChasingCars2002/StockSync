"""The "brain": turns raw Finviz data into scores, signals and a verdict.

Given a :class:`~stocksync.providers.StockData` bundle, :func:`analyze`
produces an :class:`Analysis` containing:

* **dimension scores** (0-100) across valuation, profitability, growth,
  momentum, analyst sentiment and financial health — each computed only from
  the metrics that are actually present, and each carrying its component
  scores *and* the raw display values they came from;
* a **composite score**, the availability-weighted blend of those dimensions;
* a **risk assessment** (Low / Moderate / Elevated / High) built from beta,
  volatility, short interest, leverage, liquidity and drawdown;
* plain-English **strengths and concerns** — the specific facts (with
  numbers) that most help or hurt the stock;
* a generated **thesis** — a few readable sentences tying it together,
  including whether the price action is running ahead of (or lagging) the
  fundamentals;
* a list of human-readable **signals** (bullish / bearish / neutral flags);
* a lightweight **news-sentiment** read derived from recent headlines;
* the stock's **position in its 52-week range** (0 = at the low, 100 = at
  the high);
* a one-line **verdict**.

Scoring is deliberately transparent and rule-based rather than a black box:
every number traces back to a documented threshold, so a user can sanity-check
why a stock scored the way it did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

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
    """A 0-100 score for one analytical dimension plus its contributing parts.

    ``components`` maps each contributing metric to its 0-100 sub-score;
    ``raw`` maps the same metric names to the display value they were parsed
    from (e.g. ``"P/E": "31.50"``), so a UI can show *why* a dimension scored
    the way it did.
    """

    name: str
    score: Optional[float]  # None when no underlying metric was available
    components: Dict[str, float] = field(default_factory=dict)
    raw: Dict[str, str] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.score is not None


@dataclass
class Signal:
    """A discrete, human-readable observation about the stock."""

    text: str
    sentiment: str  # "bullish" | "bearish" | "neutral"


@dataclass
class RiskAssessment:
    """A rule-based read of how much can go wrong, and why.

    ``score`` runs 0-100 where higher means riskier; ``level`` buckets it into
    Low / Moderate / Elevated / High; ``factors`` lists the specific
    contributors in plain English (highest-impact first).
    """

    level: str
    score: float
    factors: List[str] = field(default_factory=list)


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
    # Momentum-excluded score used to rank recommendations (None if no data).
    quality_score: Optional[float] = None
    # A few raw display fields surfaced for convenient rendering.
    price: Optional[str] = None
    change: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    data_errors: List[str] = field(default_factory=list)
    # Deeper, human-readable insight.
    risk: Optional[RiskAssessment] = None
    strengths: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    thesis: str = ""
    # Where the price sits in its 52-week range: 0 = at the low, 100 = at the
    # high, None when Finviz didn't report both distances.
    range_position: Optional[float] = None

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


def _raw(fundamentals: Dict[str, str], parts: Dict[str, float]) -> Dict[str, str]:
    """Collect the display values behind *parts* whose names are Finviz keys."""
    return {k: str(fundamentals[k]) for k in parts if k in fundamentals}


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
    return DimensionScore("Valuation", _mean(list(parts.values())), parts, _raw(f, parts))


def _score_profitability(f: Dict[str, str]) -> DimensionScore:
    parts: Dict[str, float] = {}
    for key in ("ROE", "ROA", "Profit Margin", "Oper. Margin"):
        val = _f(f, key)
        if val is not None:
            parts[key] = _score_linear(val, 0, 30)
    return DimensionScore("Profitability", _mean(list(parts.values())), parts, _raw(f, parts))


def _score_growth(f: Dict[str, str]) -> DimensionScore:
    parts: Dict[str, float] = {}
    for key in ("EPS next Y", "EPS next 5Y", "Sales Q/Q", "EPS Q/Q", "Sales past 5Y"):
        val = _f(f, key)
        if val is not None:
            parts[key] = _score_linear(val, -10, 30)
    return DimensionScore("Growth", _mean(list(parts.values())), parts, _raw(f, parts))


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
    return DimensionScore("Momentum", _mean(list(parts.values())), parts, _raw(f, parts))


def _analyst_upside(f: Dict[str, str]) -> Optional[float]:
    """Percent upside from current price to the mean analyst target price."""
    price = _f(f, "Price")
    target = _f(f, "Target Price")
    if price and target and price > 0:
        return (target - price) / price * 100.0
    return None


def _score_analyst(f: Dict[str, str]) -> DimensionScore:
    parts: Dict[str, float] = {}
    raw: Dict[str, str] = {}
    recom = _f(f, "Recom")
    if recom is not None:
        # Finviz Recom: 1 == Strong Buy ... 5 == Strong Sell.
        parts["Recom"] = clamp((5.0 - recom) / 4.0 * 100.0)
        raw["Recom"] = str(f.get("Recom"))
    upside = _analyst_upside(f)
    if upside is not None:
        parts["Target upside"] = _score_linear(upside, -20, 50)
        raw["Target upside"] = f"{upside:+.0f}%"
    return DimensionScore("Analyst", _mean(list(parts.values())), parts, raw)


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
    return DimensionScore("Financial Health", _mean(list(parts.values())), parts, _raw(f, parts))


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

# Quality-tilted weights: Momentum is excluded entirely so a stock that merely
# had a big day cannot rank as a strong recommendation on price action alone.
# Used to score off-watchlist recommendation candidates.
_QUALITY_WEIGHTS = {
    "Valuation": 0.20,
    "Profitability": 0.28,
    "Growth": 0.18,
    "Analyst": 0.18,
    "Financial Health": 0.16,
}


def _weighted(dimensions: List[DimensionScore], weights: Dict[str, float]) -> Optional[float]:
    num = 0.0
    den = 0.0
    for dim in dimensions:
        if dim.available and dim.name in weights:
            num += dim.score * weights[dim.name]
            den += weights[dim.name]
    if den == 0:
        return None
    return num / den


def _composite(dimensions: List[DimensionScore]) -> Optional[float]:
    return _weighted(dimensions, _WEIGHTS)


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
# Risk assessment
# ---------------------------------------------------------------------------

def _volatility(f: Dict[str, str]) -> Optional[float]:
    """Best-effort daily volatility % across the key shapes Finviz uses."""
    for key in ("Volatility M", "Volatility (Month)"):
        val = _f(f, key)
        if val is not None:
            return val
    combo = f.get("Volatility")  # sometimes "1.94% 2.41%" (week month)
    if combo:
        vals = [parse_number(part) for part in str(combo).split()]
        vals = [v for v in vals if v is not None]
        if vals:
            return max(vals)
    for key in ("Volatility W", "Volatility (Week)"):
        val = _f(f, key)
        if val is not None:
            return val
    return None


def assess_risk(f: Dict[str, str]) -> RiskAssessment:
    """Score downside risk 0-100 from volatility, leverage, crowding and losses.

    Every threshold is spelled out here so the resulting ``factors`` read as
    an explanation, not an oracle: each point of risk maps to a named cause.
    """
    score = 15.0  # base: every single stock carries some idiosyncratic risk
    factors: List[Tuple[float, str]] = []

    def add(points: float, text: str) -> None:
        nonlocal score
        score += points
        factors.append((points, text))

    beta = _f(f, "Beta")
    if beta is not None:
        if beta >= 2.0:
            add(18, f"Very high beta ({beta:.1f}) — amplifies every market move")
        elif beta >= 1.4:
            add(10, f"High beta ({beta:.1f}) — swings harder than the market")
        elif beta <= 0.7:
            score -= 6  # a genuine damper; not worth listing as a "factor"

    vol = _volatility(f)
    if vol is not None:
        if vol >= 8:
            add(16, f"Extreme daily volatility ({vol:.1f}%)")
        elif vol >= 4:
            add(8, f"Elevated daily volatility ({vol:.1f}%)")

    short = _f(f, "Short Float")
    if short is not None:
        if short >= 20:
            add(18, f"Heavily shorted ({short:.0f}% of float) — squeeze/crash prone")
        elif short >= 10:
            add(12, f"High short interest ({short:.0f}% of float)")

    deq = _f(f, "Debt/Eq")
    if deq is not None:
        if deq >= 3:
            add(14, f"Very heavy leverage (debt/equity {deq:.1f})")
        elif deq >= 1.5:
            add(7, f"Meaningful leverage (debt/equity {deq:.1f})")

    margin = _f(f, "Profit Margin")
    if margin is not None and margin < 0:
        add(14, f"Unprofitable (margin {margin:.0f}%)")

    cur = _f(f, "Current Ratio")
    if cur is not None and cur < 1.0:
        add(6, f"Thin liquidity (current ratio {cur:.2f})")

    high = _f(f, "52W High")  # % distance from the 52-week high (<= 0)
    if high is not None and high <= -40:
        add(12, f"Deep drawdown ({high:.0f}% off its 52-week high)")

    rsi = _f(f, "RSI (14)")
    if rsi is not None and rsi >= 75:
        add(5, f"Stretched near-term (RSI {rsi:.0f})")

    price = _f(f, "Price")
    if price is not None and price < 5:
        add(8, "Sub-$5 share price")

    score = clamp(score)
    if score < 30:
        level = "Low"
    elif score < 48:
        level = "Moderate"
    elif score < 65:
        level = "Elevated"
    else:
        level = "High"
    # Highest-impact causes first, so factors[0] is "the" headline risk.
    factors.sort(key=lambda t: t[0], reverse=True)
    return RiskAssessment(level, score, [text for _, text in factors])


# ---------------------------------------------------------------------------
# Strengths & concerns
# ---------------------------------------------------------------------------

def _highlights(f: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """The specific facts (with numbers) that most help or hurt the stock.

    Each rule appends ``(weight, text)``; the top few per side are returned so
    the output stays scannable. Weights order by how decisive the fact is.
    """
    plus: List[Tuple[float, str]] = []
    minus: List[Tuple[float, str]] = []

    roe = _f(f, "ROE")
    if roe is not None:
        if roe >= 25:
            plus.append((roe, f"Elite return on equity ({roe:.0f}%)"))
        elif roe < 0:
            minus.append((abs(roe) + 20, f"Destroying shareholder value (ROE {roe:.0f}%)"))

    margin = _f(f, "Profit Margin")
    if margin is not None:
        if margin >= 20:
            plus.append((margin, f"Fat profit margins ({margin:.0f}%)"))
        elif margin < 0:
            minus.append((abs(margin) + 25, f"Losing money on every sale (margin {margin:.0f}%)"))

    peg = _f(f, "PEG")
    if peg is not None and peg > 0:
        if peg < 1:
            plus.append((60, f"Growth is on sale (PEG {peg:.2f})"))
        elif peg > 3:
            minus.append((peg * 6, f"Paying far ahead of growth (PEG {peg:.1f})"))

    pe = _f(f, "P/E")
    if pe is not None and pe > 0:
        if pe < 15:
            plus.append((45, f"Cheap earnings multiple (P/E {pe:.1f})"))
        elif pe > 60:
            minus.append((pe / 3, f"Very rich earnings multiple (P/E {pe:.0f})"))

    eps5 = _f(f, "EPS next 5Y")
    if eps5 is not None:
        if eps5 >= 15:
            plus.append((eps5 + 10, f"Strong long-term earnings runway ({eps5:.0f}%/yr expected)"))
        elif eps5 < 0:
            minus.append((30, f"Earnings expected to shrink ({eps5:.0f}%/yr)"))

    sales = _f(f, "Sales Q/Q")
    if sales is not None:
        if sales >= 15:
            plus.append((sales, f"Revenue accelerating ({sales:.0f}% Q/Q)"))
        elif sales < -5:
            minus.append((abs(sales) + 10, f"Revenue shrinking ({sales:.0f}% Q/Q)"))

    deq = _f(f, "Debt/Eq")
    if deq is not None:
        if 0 <= deq < 0.3:
            plus.append((40, f"Fortress balance sheet (debt/equity {deq:.2f})"))
        elif deq > 2:
            minus.append((deq * 12, f"Debt-heavy balance sheet (debt/equity {deq:.1f})"))

    upside = _analyst_upside(f)
    if upside is not None:
        if upside >= 20:
            plus.append((upside + 15, f"Analysts see {upside:.0f}% upside to target"))
        elif upside <= -5:
            minus.append((abs(upside) + 20, f"Trading {abs(upside):.0f}% above analyst target"))

    div = _f(f, "Dividend %")
    if div is not None and div >= 3:
        plus.append((div * 8, f"Substantial dividend ({div:.1f}%)"))

    inst = _f(f, "Inst Own")
    if inst is not None and inst >= 80:
        plus.append((15, f"Strong institutional backing ({inst:.0f}% owned)"))

    sma50, sma200 = _f(f, "SMA50"), _f(f, "SMA200")
    if sma50 is not None and sma200 is not None:
        if sma50 > 0 and sma200 > 0:
            plus.append((20, "Uptrend intact — above both the 50 and 200-day"))
        elif sma50 < 0 and sma200 < 0:
            minus.append((20, "Entrenched downtrend — below both the 50 and 200-day"))

    plus.sort(key=lambda t: t[0], reverse=True)
    minus.sort(key=lambda t: t[0], reverse=True)
    return [t for _, t in plus[:4]], [t for _, t in minus[:4]]


# ---------------------------------------------------------------------------
# 52-week range position
# ---------------------------------------------------------------------------

def _range_position(f: Dict[str, str]) -> Optional[float]:
    """Where the price sits in its 52-week range (0 = low, 100 = high).

    Finviz reports the *percent distances* from the high (<= 0) and the low
    (>= 0); reconstructing relative levels from those is enough to place the
    price without knowing it.
    """
    hi = _f(f, "52W High")
    lo = _f(f, "52W Low")
    if hi is None or lo is None or hi > 0 or lo < 0:
        return None
    high_level = 1.0 / (1.0 + hi / 100.0) if hi > -100 else None
    low_level = 1.0 / (1.0 + lo / 100.0)
    if high_level is None or high_level <= low_level:
        return None
    return clamp((1.0 - low_level) / (high_level - low_level) * 100.0)


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
    if high is not None:
        if high >= -3:
            signals.append(Signal("Near 52-week high", "bullish"))
        elif high <= -50:
            signals.append(Signal(f"Down {abs(high):.0f}% from 52-week high", "bearish"))
    low = _f(f, "52W Low")    # % distance from the 52-week low (>= 0)
    if low is not None and 0 <= low <= 5:
        signals.append(Signal("Near 52-week low", "bearish"))

    sma50 = _f(f, "SMA50")
    sma200 = _f(f, "SMA200")
    if sma200 is not None:
        if sma200 > 0 and (sma50 or 0) > 0 and sma50 is not None:
            signals.append(Signal("Uptrend intact (above 50 & 200-day)", "bullish"))
        elif sma200 > 0:
            signals.append(Signal("Above 200-day average (uptrend)", "bullish"))
        elif sma200 < 0 and sma50 is not None and sma50 < 0:
            signals.append(Signal("Entrenched downtrend (below 50 & 200-day)", "bearish"))
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

    relvol = _f(f, "Rel Volume")
    if relvol is not None and relvol >= 2.5:
        signals.append(Signal(f"Unusual volume ({relvol:.1f}x normal)", "neutral"))

    earnings = str(f.get("Earnings") or "").strip()
    if earnings and earnings not in {"-", "—"}:
        signals.append(Signal(f"Earnings {earnings}", "neutral"))

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
# Thesis generation
# ---------------------------------------------------------------------------

def _thesis(
    ticker: str,
    composite: Optional[float],
    quality: Optional[float],
    dimensions: List[DimensionScore],
    risk: RiskAssessment,
    news: NewsSentiment,
    verdict: str,
) -> str:
    """Compose a few plain-English sentences summarising the whole picture."""
    if composite is None:
        return f"Not enough data to form a view on {ticker}."

    sentences: List[str] = []

    avail = [d for d in dimensions if d.available]
    opener = f"{ticker} screens {verdict.lower()} at {composite:.0f}/100"
    if len(avail) >= 2:
        best = max(avail, key=lambda d: d.score)
        worst = min(avail, key=lambda d: d.score)
        if best.score - worst.score >= 12:
            opener += (
                f", led by {best.name.lower()} ({best.score:.0f}) and held back by "
                f"{worst.name.lower()} ({worst.score:.0f})"
            )
    sentences.append(opener + ".")

    # Quality-vs-momentum divergence: is the tape ahead of, or behind, the
    # business? This is the single most decision-relevant nuance the raw
    # composite hides.
    momentum = next((d for d in dimensions if d.name == "Momentum" and d.available), None)
    if momentum is not None and quality is not None:
        gap = momentum.score - quality
        if gap >= 18:
            sentences.append(
                f"The price action is running well ahead of the fundamentals "
                f"(momentum {momentum.score:.0f} vs quality {quality:.0f}), so recent "
                f"gains lean more on sentiment than substance."
            )
        elif gap <= -18:
            sentences.append(
                f"The business scores better than the tape gives it credit for "
                f"(quality {quality:.0f} vs momentum {momentum.score:.0f}) — the "
                f"profile of an out-of-favor name rather than a broken one."
            )

    risk_sentence = f"Risk looks {risk.level.lower()}"
    if risk.factors:
        risk_sentence += f" — chiefly {risk.factors[0][0].lower()}{risk.factors[0][1:]}"
    sentences.append(risk_sentence + ".")

    if news.headlines_scored:
        sentences.append(
            f"News flow is {news.label} "
            f"({news.positive} positive vs {news.negative} negative headlines)."
        )

    return " ".join(sentences)


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
    quality = _weighted(dimensions, _QUALITY_WEIGHTS)
    news = score_news(data.news)
    signals = _signals(data, news)
    risk = assess_risk(f)
    strengths, concerns = _highlights(f)
    verdict = _verdict(composite)
    return Analysis(
        ticker=data.ticker,
        company=data.company,
        composite=composite,
        dimensions=dimensions,
        signals=signals,
        news=news,
        verdict=verdict,
        quality_score=quality,
        price=f.get("Price"),
        change=f.get("Change"),
        sector=f.get("Sector"),
        industry=f.get("Industry"),
        data_errors=list(data.errors),
        risk=risk,
        strengths=strengths,
        concerns=concerns,
        thesis=_thesis(data.ticker, composite, quality, dimensions, risk, news, verdict),
        range_position=_range_position(f),
    )
