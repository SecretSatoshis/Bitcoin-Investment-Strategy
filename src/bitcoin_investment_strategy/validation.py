"""Checks every release must pass before it is published."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import FRED_CACHE_MAX_AGE_YEARS, ROOT, last_completed_utc
from .io import sha256
from .release_files import DATA_FILES
from .savings import prepare_prices


def validate_daily_index(frame: pd.DataFrame, name: str) -> None:
    """Require nonempty, unique, ordered calendar days with no gaps."""
    index = frame.index
    if frame.empty or not isinstance(index, pd.DatetimeIndex) or index.hasnans or not index.equals(index.normalize()):
        raise ValueError(f"{name}: requires nonempty normalized daily dates")
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f"{name}: index must be unique and ordered")
    if not index.to_series().diff().dropna().eq(pd.Timedelta(days=1)).all():
        raise ValueError(f"{name}: index contains calendar gaps")


def validate_bitcoin_daily(frame: pd.DataFrame, columns=("price",)) -> None:
    """A complete daily table with the given columns, finite values and tradable prices."""
    validate_daily_index(frame, "bitcoin_daily")
    missing = set(columns).difference(frame.columns)
    if missing:
        raise ValueError(f"bitcoin_daily: missing columns {sorted(missing)}")
    prepare_prices(frame["price"])
    if np.isinf(frame.select_dtypes(include="number")).any().any():
        raise ValueError("bitcoin_daily: infinite numeric values")


def validate_release_manifest(path: Path, root: Path = ROOT, expected=DATA_FILES) -> dict:
    """Require exactly the expected artifacts, each inside `root` and matching its checksum."""
    manifest = json.loads(Path(path).read_text())
    if manifest.get("schema_version") != 1 or set(manifest.get("artifacts", {})) != set(expected):
        raise ValueError("manifest must contain the complete expected artifact set and schema version")
    for relative, metadata in manifest["artifacts"].items():
        artifact = (root / relative).resolve()
        if not artifact.is_relative_to(root.resolve()):
            raise ValueError("manifest artifact escapes release root")
        if not artifact.exists():
            raise ValueError(f"manifest artifact is missing: {relative}")
        if sha256(artifact) != metadata["sha256"]:
            raise ValueError(f"manifest checksum mismatch: {relative}")
    return manifest


def validate_income(frame: pd.DataFrame, as_of=None) -> None:
    """Unique completed years, finite positive values, and recent enough for the report date."""
    if frame.empty or not {"Year", "median_household_income_usd"}.issubset(frame.columns):
        raise ValueError("Income must contain nonempty annual observations")
    years = pd.to_numeric(frame["Year"], errors="coerce")
    values = pd.to_numeric(frame["median_household_income_usd"], errors="coerce")
    if (not np.isfinite(years).all() or not np.isfinite(values).all()
            or not years.eq(years.astype(float).round()).all()
            or years.duplicated().any() or not values.gt(0).all()):
        raise ValueError("Income requires unique integral years and finite positive values")
    cutoff = last_completed_utc() if as_of is None else pd.Timestamp(as_of)
    if years.min() < 1900 or years.max() >= cutoff.year:
        raise ValueError("Income years must be completed annual periods on the report date")
    if cutoff.year - years.max() > FRED_CACHE_MAX_AGE_YEARS:
        raise ValueError("Income observations are too old for the report date")
