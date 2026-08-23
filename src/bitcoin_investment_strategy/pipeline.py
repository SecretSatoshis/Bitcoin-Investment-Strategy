from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .config import (
    BRK_SERIES,
    MANIFEST_DIR,
    PROCESSED_DIR,
    RAW_DIR,
    ROOT,
    START_DATE,
    ensure_directories,
    last_completed_utc,
)
from .fetchers.brk import fetch_brk_daily
from .fetchers.fred import fetch_fred_median_income
from .io import atomic_write_csv, atomic_write_json, sha256
from .transforms import build_bitcoin_daily
from .validation import (
    validate_bitcoin_daily,
    validate_brk_raw,
    validate_release_manifest,
)


def _cached_fetch(
    label: str,
    fetcher: Callable[[], tuple[pd.DataFrame, dict[str, Any]]],
    cache_path: Path,
    *,
    parse_dates: list[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    try:
        frame, provenance = fetcher()
        provenance = {**provenance, "status": "live"}
        return frame, provenance
    except Exception as error:
        if not cache_path.exists():
            raise RuntimeError(f"{label}: live retrieval failed and no verified cache exists") from error
        print(f"  {label}: live retrieval failed ({error.__class__.__name__}); using committed cache")
        frame = pd.read_csv(cache_path, parse_dates=parse_dates)
        return frame, {
            "status": "cached",
            "cache_path": str(cache_path.relative_to(ROOT)),
            "live_error": f"{error.__class__.__name__}: {str(error)[:300]}",
        }


def _artifact_metadata(path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    if path.suffix == ".csv":
        frame = pd.read_csv(path)
        metadata.update({"rows": len(frame), "columns": len(frame.columns)})
        if "date" in frame.columns and len(frame):
            dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
            if len(dates):
                metadata.update({"data_start": dates.min().date().isoformat(), "data_end": dates.max().date().isoformat()})
        elif "Year" in frame.columns and len(frame):
            years = pd.to_numeric(frame["Year"], errors="coerce").dropna()
            if len(years):
                metadata.update({"data_start": str(int(years.min())), "data_end": str(int(years.max()))})
    return metadata


def _source_registry() -> pd.DataFrame:
    rows = [
        ("BRK / Bitview", "BRK daily series API", "daily", "savings", "data/processed/bitcoin_daily.csv"),
        ("FRED / U.S. Census Bureau", "MEHOINUSA646N nominal median household income", "annual", "savings", "data/processed/median_household_income_annual.csv"),
    ]
    return pd.DataFrame(rows, columns=["source", "dataset", "frequency", "consumers", "canonical_artifact"])


def _column_dictionary() -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for source_name, column in BRK_SERIES.items():
        consumers = "savings" if source_name == "price_close" else ""
        rows.append({"column": column, "upstream_series": source_name, "source": "BRK / Bitview", "consumers": consumers})
    rows.extend(
        [
            {"column": "subsidy_daily", "upstream_series": "subsidy_cumulative", "source": "derived", "consumers": ""},
            {"column": "fees_daily", "upstream_series": "fees_cumulative", "source": "derived", "consumers": ""},
            {"column": "market_cap_usd", "upstream_series": "price \u00d7 supply", "source": "derived", "consumers": ""},
            {"column": "days_since_genesis", "upstream_series": "date \u2212 2009-01-03", "source": "derived", "consumers": ""},
        ]
    )
    return pd.DataFrame(rows).drop_duplicates("column", keep="first")


def update_data(as_of: pd.Timestamp | None = None) -> dict[str, Any]:
    ensure_directories()
    as_of = (as_of or last_completed_utc()).normalize()
    retrieved_at = datetime.now(timezone.utc).isoformat()
    print(f"Building shared data release through completed UTC day {as_of.date()}")

    raw_brk, brk_provenance = fetch_brk_daily(as_of)
    validate_brk_raw(raw_brk)

    bitcoin_daily, core_end = build_bitcoin_daily(raw_brk)
    validate_bitcoin_daily(bitcoin_daily)

    fred_path = RAW_DIR / "fred" / "median_household_income.csv"
    income, fred_provenance = _cached_fetch("FRED median income", fetch_fred_median_income, fred_path)
    if income["Year"].duplicated().any() or income["median_household_income_usd"].le(0).any():
        raise ValueError("FRED median income failed annual uniqueness or positivity checks")

    raw_paths = {
        RAW_DIR / "brk" / "brk_daily.csv": raw_brk.reset_index(),
        fred_path: income,
    }
    processed_paths = {
        PROCESSED_DIR / "bitcoin_daily.csv": bitcoin_daily.reset_index(),
        PROCESSED_DIR / "median_household_income_annual.csv": income,
    }
    metadata_paths = {
        MANIFEST_DIR / "source_registry.csv": _source_registry(),
        MANIFEST_DIR / "column_dictionary.csv": _column_dictionary(),
    }
    for path, frame in {**raw_paths, **processed_paths, **metadata_paths}.items():
        atomic_write_csv(path, frame, index=False)

    artifact_paths = list(raw_paths) + list(processed_paths) + list(metadata_paths)
    artifacts = {str(path.relative_to(ROOT)): _artifact_metadata(path) for path in artifact_paths}
    fingerprint = hashlib.sha256(
        "".join(metadata["sha256"] for _, metadata in sorted(artifacts.items())).encode()
    ).hexdigest()[:12]
    release_id = f"{core_end.date().isoformat()}-{fingerprint}"
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "retrieved_at_utc": retrieved_at,
        "requested_start": START_DATE,
        "requested_end_exclusive": (as_of + pd.Timedelta(days=1)).date().isoformat(),
        "last_completed_utc_day": as_of.date().isoformat(),
        "core_data_end": core_end.date().isoformat(),
        "artifacts": artifacts,
        "sources": {
            "brk": {"status": "live", "base_url": "https://bitview.space/api", "series": brk_provenance},
            "fred_median_income": fred_provenance,
        },
    }
    manifest_path = MANIFEST_DIR / "data_manifest.json"
    atomic_write_json(manifest_path, manifest)
    validate_release_manifest(manifest_path)
    print(f"Published release {release_id}: {len(bitcoin_daily):,} core daily rows through {core_end.date()}")
    return manifest
