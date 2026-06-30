"""Persistent watchlist of tickers, stored as JSON.

The watchlist is intentionally tiny: an ordered, de-duplicated set of ticker
symbols plus optional free-text notes per ticker. It is the only mutable
user state in StockSync.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from . import config


def load_tickers_file(path) -> List[str]:
    """Read tickers from a plain-text file (one symbol per line).

    Blank lines and ``#`` comments are ignored, symbols are upper-cased and
    de-duplicated while preserving order. This is the format used for the
    repo-committed watchlist that drives the published dashboard, because it
    is trivial to edit from the GitHub website on a phone.
    """
    tickers: List[str] = []
    seen = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            symbol = line.split("#", 1)[0].strip().upper()
            if symbol and symbol not in seen:
                seen.add(symbol)
                tickers.append(symbol)
    return tickers


class Watchlist:
    """An ordered collection of ticker symbols with optional notes."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path if path is not None else config.watchlist_path()
        self._tickers: List[str] = []
        self._notes: Dict[str, str] = {}
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        # Accept both the current schema and a bare list of tickers.
        if isinstance(raw, list):
            self._tickers = [str(t).upper() for t in raw]
        elif isinstance(raw, dict):
            self._tickers = [str(t).upper() for t in raw.get("tickers", [])]
            self._notes = {str(k).upper(): str(v) for k, v in raw.get("notes", {}).items()}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump({"tickers": self._tickers, "notes": self._notes}, fh, indent=2)

    # -- queries ----------------------------------------------------------

    @property
    def tickers(self) -> List[str]:
        """The tickers in insertion order (a copy, safe to mutate)."""
        return list(self._tickers)

    def __contains__(self, ticker: str) -> bool:
        return ticker.upper().strip() in self._tickers

    def __len__(self) -> int:
        return len(self._tickers)

    def __iter__(self):
        return iter(self._tickers)

    def note(self, ticker: str) -> Optional[str]:
        return self._notes.get(ticker.upper().strip())

    # -- mutations --------------------------------------------------------

    def add(self, ticker: str, note: Optional[str] = None) -> bool:
        """Add *ticker* to the watchlist. Returns ``True`` if newly added.

        Adding an existing ticker with a note updates the note and returns
        ``False`` (it was already present).
        """
        ticker = ticker.upper().strip()
        if not ticker:
            raise ValueError("ticker must be a non-empty symbol")
        added = ticker not in self._tickers
        if added:
            self._tickers.append(ticker)
        if note:
            self._notes[ticker] = note
        self._save()
        return added

    def remove(self, ticker: str) -> bool:
        """Remove *ticker*. Returns ``True`` if it was present."""
        ticker = ticker.upper().strip()
        if ticker not in self._tickers:
            return False
        self._tickers.remove(ticker)
        self._notes.pop(ticker, None)
        self._save()
        return True

    def clear(self) -> None:
        self._tickers = []
        self._notes = {}
        self._save()
