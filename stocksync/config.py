"""Filesystem paths and small runtime settings for StockSync.

Everything user-specific lives under a single data directory so the tool
leaves no surprises elsewhere. The location can be overridden with the
``STOCKSYNC_HOME`` environment variable, which is handy for tests and for
keeping separate watchlists.
"""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """Return the directory where StockSync stores its data, creating it.

    Defaults to ``~/.stocksync`` but honours ``STOCKSYNC_HOME``.
    """
    override = os.environ.get("STOCKSYNC_HOME")
    base = Path(override).expanduser() if override else Path.home() / ".stocksync"
    base.mkdir(parents=True, exist_ok=True)
    return base


def watchlist_path() -> Path:
    """Path to the JSON file holding the watchlist."""
    return data_dir() / "watchlist.json"


def cache_path() -> Path:
    """Path to the on-disk Finviz response cache."""
    return data_dir() / "cache.json"


# How long a cached Finviz snapshot is considered fresh, in seconds.
# Fundamentals barely move intraday, so a few minutes keeps the tool snappy
# without serving stale prices for long.
CACHE_TTL_SECONDS = int(os.environ.get("STOCKSYNC_CACHE_TTL", "300"))
