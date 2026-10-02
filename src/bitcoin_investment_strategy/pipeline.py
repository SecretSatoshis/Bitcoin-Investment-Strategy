"""Fetch, check and publish the daily data release."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .config import MANIFEST_DIR, PROCESSED_DIR, ROOT, ensure_directories, last_completed_utc
from .fetchers.report_library import fetch_savings_inputs
from .io import artifact_metadata, atomic_write_csv, atomic_write_json, release_id
from .release_files import DATA_MANIFEST
from .validation import validate_bitcoin_daily, validate_income, validate_release_manifest


def _source_registry() -> pd.DataFrame:
    return pd.DataFrame(
        [("Bitcoin Report Library (BRK data)", "BTC daily closing price", "daily",
          "data/processed/bitcoin_daily.csv"),
         ("Bitcoin Report Library (FRED / U.S. Census Bureau data)",
          "MEHOINUSA646N nominal median household income", "annual",
          "data/processed/median_household_income_annual.csv")],
        columns=["source", "dataset", "frequency", "canonical_artifact"],
    )


def _column_dictionary() -> pd.DataFrame:
    return pd.DataFrame(
        [("price", "price_close", "Bitcoin Report Library (BRK data)", "BTC daily close in USD"),
         ("median_household_income_usd", "us_median_household_income_usd",
          "Bitcoin Report Library (FRED / U.S. Census Bureau data)",
          "Nominal U.S. median household income, FRED series MEHOINUSA646N")],
        columns=["column", "upstream_series", "source", "description"],
    )


def update_data(as_of: pd.Timestamp | None = None) -> dict[str, Any]:
    ensure_directories()
    as_of = (as_of or last_completed_utc()).normalize()
    if pd.isna(as_of) or as_of.tz is not None or as_of > last_completed_utc():
        raise ValueError("as_of must be a completed UTC calendar day")
    retrieved_at = datetime.now(timezone.utc).isoformat()
    print(f"Building the data release through completed UTC day {as_of.date()}")

    # Price and income come from the same Report Library release.
    daily, income, provenance = fetch_savings_inputs(as_of)
    validate_bitcoin_daily(daily)
    validate_income(income, as_of)

    outputs = {
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
        "sources": {"report_library": {"status": "live", **provenance}},
    }
    manifest_path = ROOT / DATA_MANIFEST
    atomic_write_json(manifest_path, manifest)
    validate_release_manifest(manifest_path)
    print(f"Published release {manifest['release_id']}: {len(daily):,} daily rows through {as_of.date()}")
    return manifest
