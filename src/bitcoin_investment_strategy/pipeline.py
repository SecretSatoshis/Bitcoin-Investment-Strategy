from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .config import (
    BRK_SERIES,
    FRED_CACHE_MAX_AGE_YEARS,
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
    validate_income,
    validate_brk_raw,
    validate_release_manifest,
)


def _cached_fetch(
    label: str,
    fetcher: Callable[[], tuple[pd.DataFrame, dict[str, Any]]],
    cache_path: Path,
    *,
    parse_dates: list[str] | None = None,
    fatal_errors: tuple[type[Exception], ...] = (ValueError,),
    stale_cache_check: Callable[[pd.DataFrame], str | None] | None = None,
    cache_manifest_path: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch live, falling back to the committed cache only for recoverable failures.

    Two things the bare `except Exception` could not distinguish:

    * A timeout is transient and the cache is exactly the right answer. A schema change
      is permanent — the source moved — and serving the cache turns a loud failure into
      an indefinitely frozen number. `fatal_errors` re-raises that class.
    * A cache is only a substitute while it is still current. `stale_cache_check` gives
      the caller an explicit age budget, matching how every other source in this tree
      is bounded.
    """
    try:
        frame, provenance = fetcher()
        provenance = {**provenance, "status": "live"}
        return frame, provenance
    except fatal_errors as error:
        raise RuntimeError(
            f"{label}: the source returned an unexpected schema, which the committed "
            "cache cannot stand in for — the upstream format has changed and the "
            "fetcher needs updating"
        ) from error
    except Exception as error:
        if not cache_path.exists():
            raise RuntimeError(f"{label}: live retrieval failed and no verified cache exists") from error
        print(f"  {label}: live retrieval failed ({error.__class__.__name__}); using committed cache")
        previous_path = cache_manifest_path or MANIFEST_DIR / "data_manifest.json"
        try:
            previous = json.loads(previous_path.read_text())
            relative = str(cache_path.relative_to(ROOT))
            expected = previous["artifacts"][relative]["sha256"]
            if sha256(cache_path) != expected:
                raise ValueError("checksum mismatch")
        except (OSError, KeyError, ValueError) as cache_error:
            raise RuntimeError(f"{label}: cache is not verified by the previous manifest") from cache_error
        frame = pd.read_csv(cache_path, parse_dates=parse_dates)

        if stale_cache_check is not None:
            reason = stale_cache_check(frame)
            if reason is not None:
                raise RuntimeError(
                    f"{label}: live retrieval failed and the committed cache is no "
                    f"longer usable — {reason}"
                ) from error

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


def _fred_cache_staleness(frame: pd.DataFrame, as_of: pd.Timestamp) -> str | None:
    """Return why a committed FRED cache is unusable, or ``None`` if current."""
    if "Year" not in frame.columns:
        return "it contains no usable Year column"
    years = pd.to_numeric(frame["Year"], errors="coerce").dropna()
    if years.empty:
        return "it contains no usable Year column"
    age = int(as_of.year) - int(years.max())
    if age > FRED_CACHE_MAX_AGE_YEARS:
        return (
            f"its newest observation is {int(years.max())}, {age} years behind "
            f"{as_of.year} (limit {FRED_CACHE_MAX_AGE_YEARS})"
        )
    return None


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
    if pd.isna(as_of) or as_of.tz is not None or as_of > last_completed_utc():
        raise ValueError("as_of must be a completed UTC calendar day")
    retrieved_at = datetime.now(timezone.utc).isoformat()
    print(f"Building shared data release through completed UTC day {as_of.date()}")

    raw_brk, brk_provenance = fetch_brk_daily(as_of)
    validate_brk_raw(raw_brk)

    bitcoin_daily, core_end = build_bitcoin_daily(raw_brk)
    if core_end != as_of:
        raise ValueError(f"Required BRK series end at {core_end.date()}, expected {as_of.date()}; refusing truncated release")
    validate_bitcoin_daily(bitcoin_daily)

    fred_path = RAW_DIR / "fred" / "median_household_income.csv"
    income, fred_provenance = _cached_fetch(
        "FRED median income",
        fetch_fred_median_income,
        fred_path,
        stale_cache_check=lambda frame: _fred_cache_staleness(frame, as_of),
    )
    validate_income(income, as_of)

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
