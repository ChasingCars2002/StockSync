"""StockSync — a stock watchlist "brain" that aggregates news and financial
metrics via Finviz and turns them into scores, signals and a verdict.

Public API::

    from stocksync import FinvizProvider, Watchlist, analyze

    provider = FinvizProvider()
    data = provider.fetch("AAPL")
    analysis = analyze(data)
    print(analysis.composite, analysis.verdict)
"""

from .brain import Analysis, analyze, score_news
from .providers import FinvizProvider, StockData
from .watchlist import Watchlist

__version__ = "0.1.0"

__all__ = [
    "Analysis",
    "analyze",
    "score_news",
    "FinvizProvider",
    "StockData",
    "Watchlist",
    "__version__",
]
