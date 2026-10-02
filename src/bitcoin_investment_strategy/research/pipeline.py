"""Fetch, check and write the supply and demand data release in data/research/.

Everything comes from the same Bitcoin Report Library release as the savings data:

  bitcoin_daily.csv               on-chain series, daily flows and mining efficiency
  technology_adoption_annual.csv  world internet users and population by year
  bitcoin_owner_estimates.csv     yearly estimates of bitcoin owners
  etf_daily.csv, etf_totals_daily.csv, etf_quarterly.csv   the release's US spot ETF tables

Company and government treasuries are not part of the release: the demand notebook reads
them from CoinGecko when it runs (see treasuries.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ..config import ROOT, last_completed_utc
from ..fetchers.report_library import fetch_release_files
from ..io import artifact_metadata, atomic_write_csv, atomic_write_json, release_id
from .config import (
    ETF_FILES, FLOW_SERIES, MANIFEST_DIR, REPORT_LIBRARY_COLUMNS, REPORT_LIBRARY_SERIES, RESEARCH_DIR,
    RESEARCH_MANIFEST, UNDER_AGE_SUPPLY,
)
from .transforms import build_bitcoin_daily, build_owner_estimates, build_technology_adoption
from .validation import validate_bitcoin_daily, validate_etf, validate_release_manifest, validate_technology


def _source_registry() -> pd.DataFrame:
    rows = [
        ("Bitcoin Report Library (BRK data)", "on-chain daily series", "daily", "data/research/bitcoin_daily.csv"),
        ("Bitcoin Report Library (Coin Metrics Labs data)", "network mining efficiency", "monthly",
         "data/research/bitcoin_daily.csv"),
        ("Bitcoin Report Library (World Bank and Our World in Data)", "internet users and population", "annual",
         "data/research/technology_adoption_annual.csv"),
        ("Bitcoin Report Library (Crypto.com estimates)", "bitcoin-owner estimates", "sparse annual",
         "data/research/bitcoin_owner_estimates.csv"),
        ("Bitcoin Report Library (ETF issuers and SEC filings)", "US spot ETF holdings, flows and reported cost",
         "daily", ";".join(f"data/research/{name}" for name in ETF_FILES)),
    ]
    return pd.DataFrame(rows, columns=["source", "dataset", "frequency", "canonical_artifact"])


def _column_dictionary() -> pd.DataFrame:
    rows = [(column, upstream, "Bitcoin Report Library") for upstream, column in REPORT_LIBRARY_SERIES.items()]
    rows += [(over, f"supply - {under}", "derived") for over, under in UNDER_AGE_SUPPLY.items()]
    rows += [(cumulative, cumulative, "Bitcoin Report Library") for cumulative in FLOW_SERIES.values()]
    rows += [(column, f"daily difference of {cumulative}", "derived") for column, cumulative in FLOW_SERIES.items()]
    rows += [
        ("market_cap_usd", "price x supply", "derived"),
        ("days_since_genesis", "date - 2009-01-03", "derived"),
    ]
    return pd.DataFrame(rows, columns=["column", "upstream_series", "source"])


def update_research_data(as_of: pd.Timestamp | None = None) -> dict[str, Any]:
    """Build and write the release through `as_of` (default: the last completed UTC day)."""
    as_of = (as_of or last_completed_utc()).normalize()
    if pd.isna(as_of) or as_of.tz is not None or as_of > last_completed_utc():
        raise ValueError("as_of must be a completed UTC day")
    retrieved_at = datetime.now(timezone.utc).isoformat()
    print(f"Building the supply and demand release through completed UTC day {as_of.date()}")

    master, annual, etf, provenance = fetch_release_files(as_of, REPORT_LIBRARY_COLUMNS, ETF_FILES)
    bitcoin_daily = build_bitcoin_daily(master, as_of)
    if bitcoin_daily.index[-1] != as_of:
        raise ValueError(f"The Report Library release ends {bitcoin_daily.index[-1].date()}, expected {as_of.date()}")
    validate_bitcoin_daily(bitcoin_daily)
    technology = build_technology_adoption(annual)
    validate_technology(technology)
    owners = build_owner_estimates(annual)
    etf = {name: table.assign(**{column: pd.to_datetime(table[column])
                                 for column in ("date", "quarter_end", "trade_date") if column in table})
           for name, table in etf.items()}
    validate_etf(etf)

    efficiency_end = pd.Timestamp(master["cm_efficiency_source_date"].dropna().iloc[-1])
    outputs = {
        RESEARCH_DIR / "bitcoin_daily.csv": bitcoin_daily.reset_index(),
        RESEARCH_DIR / "technology_adoption_annual.csv": technology,
        RESEARCH_DIR / "bitcoin_owner_estimates.csv": owners,
        **{RESEARCH_DIR / name: table for name, table in etf.items()},
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
        "core_data_end": as_of.date().isoformat(),
        "artifacts": artifacts,
        "sources": {
            "report_library": {"status": "live", **provenance},
            "coinmetrics_efficiency": {"observation_end": efficiency_end.date().isoformat(),
                                       "carried_days": (as_of - efficiency_end).days, "maximum_carry_days": 365},
        },
    }
    atomic_write_json(RESEARCH_MANIFEST, manifest)
    validate_release_manifest(RESEARCH_MANIFEST)
    print(f"Published release {manifest['release_id']}: {len(bitcoin_daily):,} daily rows through {as_of.date()}")
    return manifest
