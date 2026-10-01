"""Paths, sources and release rules."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MANIFEST_DIR = DATA_DIR / "manifests"

REPORT_LIBRARY_URL = "https://secretsatoshis.github.io/Bitcoin-Report-Library/csv"
FRED_MEDIAN_INCOME_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MEHOINUSA646N"

# MEHOINUSA646N is annual and published about a year late, so the newest year in a
# healthy copy is normally the prior year. Three years allows for that lag plus a late
# release; anything older would present a frozen figure as current.
FRED_CACHE_MAX_AGE_YEARS = 3


def last_completed_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)


def ensure_directories() -> None:
    for path in (RAW_DIR, PROCESSED_DIR, MANIFEST_DIR):
        path.mkdir(parents=True, exist_ok=True)
