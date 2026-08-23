from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BRK_SERIES, COHORTS, FLOW_SERIES, KNOWN_NO_BLOCK_DATES, ROOT
from .io import sha256


def _daily_index(frame: pd.DataFrame, name: str) -> None:
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{name}: index must be unique and ordered")
    gaps = frame.index.to_series().diff().dropna()
    if not gaps.eq(pd.Timedelta(days=1)).all():
        raise ValueError(f"{name}: index contains calendar gaps")


def validate_brk_raw(frame: pd.DataFrame) -> None:
    _daily_index(frame, "BRK raw")
    missing = set(BRK_SERIES).difference(frame.columns)
    if missing:
        raise ValueError(f"BRK raw: missing columns {sorted(missing)}")
    quiet = frame.index[frame["supply"].isna()]
    if not quiet.equals(KNOWN_NO_BLOCK_DATES):
        raise ValueError(f"BRK raw: unexpected supply gaps {list(quiet[:10])}")
    for column in BRK_SERIES:
        series = frame[column].drop(index=KNOWN_NO_BLOCK_DATES, errors="ignore")
        first, last = series.first_valid_index(), series.last_valid_index()
        if first is None:
            raise ValueError(f"BRK raw: {column} is all-null")
        if series.loc[first:last].isna().any():
            date = series.loc[first:last].index[series.loc[first:last].isna()][0]
            raise ValueError(f"BRK raw: {column} has an internal gap on {date.date()}")


def validate_bitcoin_daily(frame: pd.DataFrame) -> None:
    _daily_index(frame, "bitcoin_daily")
    required = set(BRK_SERIES.values()) | set(FLOW_SERIES) | {
        "market_cap_usd",
        "days_since_genesis",
        "years_since_genesis",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"bitcoin_daily: missing columns {sorted(missing)}")
    subsidy_restart = frame.loc[pd.Timestamp("2009-01-09"), "subsidy_daily"]
    if not np.isclose(subsidy_restart, 700.0):
        raise ValueError(f"bitcoin_daily: expected 700 BTC on 2009-01-09, got {subsidy_restart}")
    first_1y = frame.index[frame["utxos_over_1y_old_supply"].gt(0)][0]
    if first_1y != pd.Timestamp("2010-01-09"):
        raise ValueError(f"bitcoin_daily: first positive 1y+ cohort is {first_1y.date()}")
    for column in FLOW_SERIES:
        if frame[column].dropna().lt(-1e-7).any():
            raise ValueError(f"bitcoin_daily: negative flow in {column}")
    thresholds = [frame[f"utxos_over_{age}_old_supply"] for age in COHORTS]
    for younger, older in zip(thresholds, thresholds[1:]):
        valid = younger.notna() & older.notna()
        if older[valid].gt(younger[valid] + 1e-6).any():
            raise ValueError("bitcoin_daily: age-cohort nesting is violated")


def validate_release_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text())
    for relative, metadata in manifest["artifacts"].items():
        artifact = ROOT / relative
        if not artifact.exists():
            raise ValueError(f"manifest artifact is missing: {relative}")
        if sha256(artifact) != metadata["sha256"]:
            raise ValueError(f"manifest checksum mismatch: {relative}")
    return manifest
