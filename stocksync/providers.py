"""Data access layer that wraps the ``finviz`` package.

The rest of StockSync never imports ``finviz`` directly. It goes through
:class:`FinvizProvider`, which adds three things on top of the raw library:

* **A uniform return shape** — every fetch returns a :class:`StockData`
  bundle, with empty collections rather than exceptions when a sub-feed
  fails, so a single flaky endpoint never sinks a whole report.
* **On-disk caching** with a TTL, so repeatedly viewing a watchlist does not
  hammer Finviz (and works offline once warmed).
* **Dependency injection** — the underlying fetch functions can be supplied
  explicitly, which keeps the provider fully testable without network access.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import config


@dataclass
class StockData:
    """Everything StockSync knows about a single ticker at a point in time."""

    ticker: str
    fundamentals: Dict[str, str] = field(default_factory=dict)
    news: List[Tuple[str, str, str, str]] = field(default_factory=list)
    analyst_ratings: List[Dict[str, str]] = field(default_factory=list)
    insider: List[Dict[str, str]] = field(default_factory=list)
    fetched_at: float = 0.0
    # Names of sub-feeds that failed to load (for transparent reporting).
    errors: List[str] = field(default_factory=list)

    @property
    def company(self) -> str:
        return self.fundamentals.get("Company", "")

    @property
    def ok(self) -> bool:
        """True when at least the fundamentals snapshot loaded."""
        return bool(self.fundamentals)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "fundamentals": self.fundamentals,
            "news": [list(item) for item in self.news],
            "analyst_ratings": self.analyst_ratings,
            "insider": self.insider,
            "fetched_at": self.fetched_at,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "StockData":
        return cls(
            ticker=raw["ticker"],
            fundamentals=raw.get("fundamentals", {}),
            news=[tuple(item) for item in raw.get("news", [])],
            analyst_ratings=raw.get("analyst_ratings", []),
            insider=raw.get("insider", []),
            fetched_at=raw.get("fetched_at", 0.0),
            errors=raw.get("errors", []),
        )


# Type aliases for the injectable fetch callables.
StockFetcher = Callable[[str], Dict[str, str]]
NewsFetcher = Callable[[str], List[Tuple[str, str, str, str]]]
RatingsFetcher = Callable[[str], List[Dict[str, str]]]
InsiderFetcher = Callable[[str], List[Dict[str, str]]]


class FinvizProvider:
    """Fetches and caches stock data via Finviz.

    All four fetch functions can be injected; when omitted they are resolved
    lazily from the ``finviz`` package on first use, so importing this module
    never requires ``finviz`` to be installed.
    """

    def __init__(
        self,
        *,
        get_stock: Optional[StockFetcher] = None,
        get_news: Optional[NewsFetcher] = None,
        get_analyst_price_targets: Optional[RatingsFetcher] = None,
        get_insider: Optional[InsiderFetcher] = None,
        cache_path: Optional[Path] = None,
        ttl_seconds: Optional[int] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._get_stock = get_stock
        self._get_news = get_news
        self._get_ratings = get_analyst_price_targets
        self._get_insider = get_insider
        self._cache_path = Path(cache_path) if cache_path is not None else config.cache_path()
        self._ttl = config.CACHE_TTL_SECONDS if ttl_seconds is None else ttl_seconds
        self._clock = clock
        self._cache: Dict[str, dict] = self._load_cache()

    # -- finviz lazy resolution ------------------------------------------

    def _resolve(self, attr: str, override: Optional[Callable]) -> Callable:
        if override is not None:
            return override
        import finviz  # imported lazily; only needed for live fetches

        return getattr(finviz, attr)

    # -- caching ----------------------------------------------------------

    def _load_cache(self) -> Dict[str, dict]:
        try:
            with open(self._cache_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_path, "w", encoding="utf-8") as fh:
                json.dump(self._cache, fh)
        except OSError:
            # Caching is a best-effort optimisation; never fail a fetch over it.
            pass

    def _fresh_cached(self, ticker: str) -> Optional[StockData]:
        entry = self._cache.get(ticker.upper())
        if not entry:
            return None
        age = self._clock() - entry.get("fetched_at", 0.0)
        if age > self._ttl:
            return None
        return StockData.from_dict(entry)

    # -- public API -------------------------------------------------------

    def fetch(self, ticker: str, *, use_cache: bool = True) -> StockData:
        """Fetch a full :class:`StockData` bundle for *ticker*.

        Each sub-feed is fetched independently; a failure in one (e.g. no
        insider data) is recorded in ``errors`` but does not prevent the
        others from loading.
        """
        ticker = ticker.upper().strip()

        if use_cache:
            cached = self._fresh_cached(ticker)
            if cached is not None:
                return cached

        data = StockData(ticker=ticker, fetched_at=self._clock())

        try:
            data.fundamentals = self._resolve("get_stock", self._get_stock)(ticker) or {}
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            data.errors.append(f"fundamentals: {exc}")

        try:
            data.news = self._resolve("get_news", self._get_news)(ticker) or []
        except Exception as exc:  # noqa: BLE001
            data.errors.append(f"news: {exc}")

        try:
            data.analyst_ratings = (
                self._resolve("get_analyst_price_targets", self._get_ratings)(ticker) or []
            )
        except Exception as exc:  # noqa: BLE001
            data.errors.append(f"analyst_ratings: {exc}")

        try:
            data.insider = self._resolve("get_insider", self._get_insider)(ticker) or []
        except Exception as exc:  # noqa: BLE001
            data.errors.append(f"insider: {exc}")

        if data.ok:
            self._cache[ticker] = data.to_dict()
            self._save_cache()

        return data
