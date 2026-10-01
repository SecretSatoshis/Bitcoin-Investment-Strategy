"""Fetch, check and publish the daily data release."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .config import (
    FRED_CACHE_MAX_AGE_YEARS, MANIFEST_DIR, PROCESSED_DIR, RAW_DIR, ROOT, ensure_directories,
    last_completed_utc,
)
from .fetchers.fred import fetch_fred_median_income
from .fetchers.report_library import fetch_bitcoin_price
from .io import SourceSchemaError, artifact_metadata, atomic_write_csv, atomic_write_json, release_id, sha256
from .release_files import DATA_MANIFEST
from .validation import validate_bitcoin_daily, validate_income, validate_release_manifest


def cached_fetch(
    label: str,
    fetcher: Callable[[], tuple[pd.DataFrame, dict[str, Any]]],
    cache_path: Path,
    *,
    root: Path = ROOT,
    manifest_path: Path | None = None,
    offline: bool = False,
    parse_dates: list[str] | None = None,
    stale_cache_check: Callable[[pd.DataFrame], str | None] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch live, or reuse the saved copy the previous release manifest verifies.

    The saved copy stands in for a failed fetch (or every fetch when `offline`), but never
    for a SourceSchemaError: a changed upstream format must fail loudly rather than freeze
    the data. `stale_cache_check` returns a reason when the saved copy is too old to use.
    """
    live_error = None
    if not offline:
        try:
            frame, provenance = fetcher()
            return frame, {**provenance, "status": "live"}
        except SourceSchemaError as error:
            raise RuntimeError(
                f"{label}: the source returned an unexpected schema; the fetcher needs updating"
            ) from error
        except Exception as error:
            live_error = error
            print(f"  {label}: live retrieval failed ({error.__class__.__name__}); using the saved copy")
    relative = str(cache_path.relative_to(root))
    try:
        previous = json.loads((manifest_path or root / DATA_MANIFEST).read_text())
        if sha256(cache_path) != previous["artifacts"][relative]["sha256"]:
            raise ValueError("checksum mismatch")
    except (OSError, KeyError, ValueError) as cache_error:
        raise RuntimeError(f"{label}: saved copy is not verified by the previous manifest") from (live_error or cache_error)
    frame = pd.read_csv(cache_path, parse_dates=parse_dates)
    if stale_cache_check is not None:
        reason = stale_cache_check(frame)
        if reason is not None:
            raise RuntimeError(f"{label}: the saved copy is no longer usable — {reason}") from live_error
    provenance = {"status": "cached", "cache_path": relative}
    if live_error is not None:
        provenance["live_error"] = f"{live_error.__class__.__name__}: {str(live_error)[:300]}"
    return frame, provenance


def _fred_cache_staleness(frame: pd.DataFrame, as_of: pd.Timestamp) -> str | None:
    """Why a saved FRED copy is unusable, or None if it is recent enough."""
    years = pd.to_numeric(frame.get("Year", pd.Series(dtype=float)), errors="coerce").dropna()
    if years.empty:
        return "it contains no usable Year column"
    age = int(as_of.year) - int(years.max())
    if age > FRED_CACHE_MAX_AGE_YEARS:
        return (f"its newest observation is {int(years.max())}, {age} years behind "
                f"{as_of.year} (limit {FRED_CACHE_MAX_AGE_YEARS})")
    return None


def _source_registry() -> pd.DataFrame:
    return pd.DataFrame(
        [("Bitcoin Report Library (BRK data)", "BTC daily closing price", "daily",
          "data/processed/bitcoin_daily.csv"),
         ("FRED / U.S. Census Bureau", "MEHOINUSA646N nominal median household income", "annual",
          "data/processed/median_household_income_annual.csv")],
        columns=["source", "dataset", "frequency", "canonical_artifact"],
    )


def _column_dictionary() -> pd.DataFrame:
    return pd.DataFrame(
        [("price", "price_close", "Bitcoin Report Library (BRK data)", "BTC daily close in USD"),
         ("median_household_income_usd", "MEHOINUSA646N", "FRED / U.S. Census Bureau",
          "Nominal U.S. median household income")],
        columns=["column", "upstream_series", "source", "description"],
    )


def update_data(as_of: pd.Timestamp | None = None) -> dict[str, Any]:
    ensure_directories()
    as_of = (as_of or last_completed_utc()).normalize()
    if pd.isna(as_of) or as_of.tz is not None or as_of > last_completed_utc():
        raise ValueError("as_of must be a completed UTC calendar day")
    retrieved_at = datetime.now(timezone.utc).isoformat()
    print(f"Building the data release through completed UTC day {as_of.date()}")

    daily, price_provenance = fetch_bitcoin_price(as_of)
    validate_bitcoin_daily(daily)

    fred_path = RAW_DIR / "fred" / "median_household_income.csv"
    income, fred_provenance = cached_fetch(
        "FRED median income", fetch_fred_median_income, fred_path,
        stale_cache_check=lambda frame: _fred_cache_staleness(frame, as_of),
    )
    validate_income(income, as_of)

    outputs = {
        fred_path: income,
        PROCESSED_DIR / "bitcoin_daily.csv": daily.reset_index(),
        PROCESSED_DIR / "median_household_income_annual.csv": income,
        MANIFEST_DIR / "source_registry.csv": _source_registry(),
        MANIFEST_DIR / "column_dictionary.csv": _column_dictionary(),
    }
    for path, frame in outputs.items():
        atomic_write_csv(path, frame, index=False)

    artifacts = {str(path.relative_to(ROOT)): artifact_metadata(path) for path in outputs}
    manifest = {
        "schema_version": 1,
        "release_id": release_id(as_of, artifacts),
        "retrieved_at_utc": retrieved_at,
        "last_completed_utc_day": as_of.date().isoformat(),
        "core_data_end": as_of.date().isoformat(),
        "artifacts": artifacts,
        "sources": {
            "report_library": {"status": "live", **price_provenance},
            "fred_median_income": fred_provenance,
        },
    }
    manifest_path = ROOT / DATA_MANIFEST
    atomic_write_json(manifest_path, manifest)
    validate_release_manifest(manifest_path)
    print(f"Published release {manifest['release_id']}: {len(daily):,} daily rows through {as_of.date()}")
    return manifest
