"""Paths, sources and release rules."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
MANIFEST_DIR = DATA_DIR / "manifests"

REPORT_LIBRARY_URL = "https://secretsatoshis.github.io/Bitcoin-Report-Library/csv"

# Median income (FRED MEHOINUSA646N) is annual and published about a year late, so its
# newest year is normally the prior one. Three years allows for that lag plus a late
# release; anything older would present a frozen figure as current.
INCOME_MAX_AGE_YEARS = 3


def last_completed_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)


def ensure_directories() -> None:
    for path in (PROCESSED_DIR, MANIFEST_DIR):
        path.mkdir(parents=True, exist_ok=True)
