"""Terminal rendering for analyses and watchlist dashboards.

Pure-Python, no third-party rendering dependency. Colour is emitted with ANSI
escapes and can be disabled (``color=False``) for piping to files or for
environments that do not support it.
"""

from __future__ import annotations

from typing import List, Optional

from .brain import Analysis
from .metrics import parse_number

# ANSI colour codes, looked up by semantic name.
_COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "grey": "\033[90m",
}


def _paint(text: str, color: bool, *names: str) -> str:
    if not color or not names:
        return text
    prefix = "".join(_COLORS.get(n, "") for n in names)
    return f"{prefix}{text}{_COLORS['reset']}"


def _pad(text: str, width: int, *, align: str = "left") -> str:
    """Pad *text* to *width* based on its visible length.

    The text may already contain ANSI codes; padding is computed from the
    visible characters so columns line up regardless of colour.
    """
    visible = _visible_len(text)
    gap = max(0, width - visible)
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def _visible_len(text: str) -> int:
    """Length of *text* ignoring ANSI escape sequences."""
    out = 0
    i = 0
    while i < len(text):
        if text[i] == "\033":
            # Skip until the terminating 'm'.
            while i < len(text) and text[i] != "m":
                i += 1
            i += 1
            continue
        out += 1
        i += 1
    return out


def _score_color(score: Optional[float]) -> str:
    if score is None:
        return "grey"
    if score >= 60:
        return "green"
    if score >= 45:
        return "yellow"
    return "red"


def _bar(score: Optional[float], width: int = 20) -> str:
    if score is None:
        return "·" * width
    filled = int(round(score / 100.0 * width))
    return "█" * filled + "░" * (width - filled)


def _fmt_score(score: Optional[float]) -> str:
    return "  n/a" if score is None else f"{score:5.1f}"


def _sentiment_color(sentiment: str) -> str:
    return {"bullish": "green", "bearish": "red"}.get(sentiment, "yellow")


_RISK_COLORS = {"Low": "green", "Moderate": "yellow", "Elevated": "yellow", "High": "red"}


def _wrap(text: str, width: int) -> List[str]:
    """Simple greedy word-wrap (no textwrap dependency on ANSI-free text)."""
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def render_analysis(analysis: Analysis, *, color: bool = True, note: Optional[str] = None) -> str:
    """Render a detailed, multi-line report for a single ticker."""
    lines: List[str] = []

    header = analysis.ticker
    if analysis.company:
        header += f"  —  {analysis.company}"
    lines.append(_paint(header, color, "bold", "cyan"))

    comp_col = _score_color(analysis.composite)
    comp_txt = "n/a" if analysis.composite is None else f"{analysis.composite:.1f}/100"
    price_bit = ""
    if analysis.price:
        chg = f" ({analysis.change})" if analysis.change else ""
        price_bit = "   " + _paint(f"{analysis.price}{chg}", color, "dim")
    risk_bit = ""
    if analysis.risk is not None:
        risk_col = _RISK_COLORS.get(analysis.risk.level, "yellow")
        risk_bit = "   " + _paint(f"Risk: {analysis.risk.level}", color, risk_col)
    lines.append(
        _paint("Score: ", color, "bold")
        + _paint(comp_txt, color, "bold", comp_col)
        + "   "
        + _paint(f"[{analysis.verdict}]", color, comp_col)
        + risk_bit
        + price_bit
    )
    if note:
        lines.append(_paint(f"Note: {note}", color, "dim"))
    lines.append("")

    if analysis.thesis:
        lines.append(_paint("Read", color, "bold"))
        lines.extend("  " + ln for ln in _wrap(analysis.thesis, 76))
        lines.append("")

    lines.append(_paint("Dimensions", color, "bold"))
    for dim in analysis.dimensions:
        col = _score_color(dim.score)
        meter = _paint(_bar(dim.score), color, col)
        lines.append(f"  {dim.name:<18} {meter} {_fmt_score(dim.score)}")
    lines.append("")

    if analysis.strengths or analysis.concerns:
        if analysis.strengths:
            lines.append(_paint("Strengths", color, "bold"))
            for s in analysis.strengths:
                lines.append("  " + _paint(f"+ {s}", color, "green"))
        if analysis.concerns:
            lines.append(_paint("Concerns", color, "bold"))
            for c in analysis.concerns:
                lines.append("  " + _paint(f"- {c}", color, "red"))
        lines.append("")

    if analysis.risk is not None and analysis.risk.factors:
        risk_col = _RISK_COLORS.get(analysis.risk.level, "yellow")
        lines.append(
            _paint("Risk factors ", color, "bold")
            + _paint(f"[{analysis.risk.level}]", color, risk_col)
        )
        for factor in analysis.risk.factors[:4]:
            lines.append("  " + _paint(f"! {factor}", color, risk_col))
        lines.append("")

    if analysis.signals:
        lines.append(_paint("Signals", color, "bold"))
        for sig in analysis.signals:
            marker = {"bullish": "▲", "bearish": "▼"}.get(sig.sentiment, "•")
            col = _sentiment_color(sig.sentiment)
            lines.append("  " + _paint(f"{marker} {sig.text}", color, col))
        lines.append("")

    news = analysis.news
    if news.headlines_scored:
        col = _score_color(news.score)
        lines.append(
            _paint("News sentiment: ", color, "bold")
            + _paint(f"{news.label} ", color, col)
            + _paint(f"(+{news.positive}/-{news.negative} of {news.headlines_scored} headlines)", color, "dim")
        )

    if analysis.data_errors:
        lines.append(
            _paint(f"({len(analysis.data_errors)} data feed(s) unavailable)", color, "dim")
        )

    return "\n".join(lines)


def render_headlines(news: list, limit: int = 5, *, color: bool = True) -> str:
    """Render the latest N news headlines."""
    if not news:
        return _paint("  (no recent headlines)", color, "dim")
    lines = []
    for item in news[:limit]:
        ts = item[0] if len(item) > 0 else ""
        headline = item[1] if len(item) > 1 else ""
        source = item[3] if len(item) > 3 else ""
        src = _paint(f" ({source})", color, "grey") if source else ""
        stamp = _paint(f"[{ts}]", color, "dim")
        lines.append(f"  • {stamp} {headline}{src}")
    return "\n".join(lines)


def render_dashboard(analyses: List[Analysis], *, color: bool = True) -> str:
    """Render a compact one-row-per-ticker table sorted by composite score."""
    ranked = sorted(
        analyses,
        key=lambda a: (a.composite if a.composite is not None else -1),
        reverse=True,
    )

    cols = [
        ("TICKER", 8, "left"),
        ("SCORE", 7, "right"),
        ("VERDICT", 17, "left"),
        ("PRICE", 10, "right"),
        ("CHG", 9, "right"),
        ("NEWS", 9, "left"),
        ("TOP SIGNAL", 0, "left"),
    ]
    header = "  ".join(_pad(name, w, align=a) if w else name for name, w, a in cols)
    lines = [_paint(header, color, "bold"), _paint("─" * max(len(header), 60), color, "grey")]

    for a in ranked:
        comp_col = _score_color(a.composite)
        score_txt = "n/a" if a.composite is None else f"{a.composite:.1f}"
        change = a.change or "-"
        chg_val = parse_number(change)
        chg_col = "green" if (chg_val or 0) > 0 else "red" if (chg_val or 0) < 0 else "grey"
        top_signal = a.signals[0].text if a.signals else "-"
        top_col = _sentiment_color(a.signals[0].sentiment) if a.signals else "grey"

        cells = [
            _pad(_paint(a.ticker, color, "cyan", "bold"), 8, align="left"),
            _pad(_paint(score_txt, color, comp_col), 7, align="right"),
            _pad(a.verdict, 17, align="left"),
            _pad(a.price or "-", 10, align="right"),
            _pad(_paint(change, color, chg_col), 9, align="right"),
            _pad(_paint(a.news.label, color, _score_color(a.news.score)), 9, align="left"),
            _paint(top_signal, color, top_col),
        ]
        lines.append("  ".join(cells))

    return "\n".join(lines)
