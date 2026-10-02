"""Checks the supply and demand release must pass, built on the package's release checks."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .. import validation as core
from ..config import ROOT
from ..release_files import RESEARCH_FILES
from .analysis import COHORT_TOLERANCE_BTC, validate_cohorts
from .config import COHORTS, FLOW_SERIES, REPORT_LIBRARY_SERIES, UNDER_AGE_SUPPLY

DERIVED_COLUMNS = ("market_cap_usd", "days_since_genesis")
JURISDICTIONS = {"national", "sub_national", "not_state"}


def validate_release_manifest(path: Path) -> dict:
    return core.validate_release_manifest(path, root=ROOT, expected=RESEARCH_FILES)


def validate_bitcoin_daily(frame: pd.DataFrame) -> None:
    columns = [*REPORT_LIBRARY_SERIES.values(), *UNDER_AGE_SUPPLY, *FLOW_SERIES.values(), *FLOW_SERIES,
               *DERIVED_COLUMNS]
    core.validate_bitcoin_daily(frame, columns=columns)
    # Every on-chain series reaches the cutoff; mining efficiency is monthly and carried.
    unfinished = [column for column in columns if column != "cm_efficiency_j_gh" and pd.isna(frame[column].iloc[-1])]
    if unfinished:
        raise ValueError(f"bitcoin_daily: no value on the last day for {unfinished}")
    if not np.allclose(frame["market_cap_usd"], frame["price"] * frame["supply"],
                       rtol=1e-9, atol=1e-6, equal_nan=True):
        raise ValueError("bitcoin_daily: market cap disagrees with price times supply")
    # The first coins turned one year old a year after the 14 blocks of 2009-01-09.
    if frame.index[frame["utxos_over_1y_old_supply"].gt(0)][0] != pd.Timestamp("2010-01-09"):
        raise ValueError("bitcoin_daily: the first 1y+ cohort should appear on 2010-01-09")
    # Running totals never fall, so no daily flow is negative.
    for column in FLOW_SERIES:
        if frame[column].dropna().lt(0).any():
            raise ValueError(f"bitcoin_daily: negative flow in {column}")
    thresholds = [frame[f"utxos_over_{age}_old_supply"] for age in COHORTS]
    for younger, older in zip(thresholds, thresholds[1:]):
        valid = younger.notna() & older.notna()
        if older[valid].gt(younger[valid] + COHORT_TOLERANCE_BTC).any():
            raise ValueError("bitcoin_daily: age-cohort nesting is violated")
    validate_cohorts(frame)
    efficiency = frame["cm_efficiency_j_gh"].dropna()
    if efficiency.empty or not np.isfinite(efficiency).all() or not efficiency.gt(0).all():
        raise ValueError("Invalid mining efficiency")


def validate_etf(tables: dict[str, pd.DataFrame]) -> None:
    """The ETF tables: complete trading days, totals equal to the sum of funds, no negative holdings."""
    daily, totals = tables["etf_daily.csv"], tables["etf_totals_daily.csv"]
    if daily.empty or daily.duplicated(["fund", "date"]).any():
        raise ValueError("ETF: empty, or a fund repeats a date")
    if not np.isfinite(daily["btc_held"]).all() or daily["btc_held"].lt(0).any():
        raise ValueError("ETF: missing or negative holdings")
    summed = daily.groupby("date")["btc_held"].sum().reindex(totals["date"]).to_numpy()
    if not np.allclose(summed, totals["total_btc"], rtol=1e-9):
        raise ValueError("ETF: totals disagree with the sum of funds")
    if not totals["date"].is_monotonic_increasing or totals["date"].duplicated().any():
        raise ValueError("ETF: totals dates must be unique and ordered")
    share = daily.groupby("date")["market_share_pct"].sum()
    if not np.allclose(share, 100):
        raise ValueError("ETF: market shares do not sum to 100%")


def validate_technology(frame: pd.DataFrame) -> None:
    if frame["Year"].duplicated().any() or not frame["Year"].is_monotonic_increasing:
        raise ValueError("technology adoption: years must be unique and ordered")
    early = frame.loc[frame["Year"].between(1990, 2004), "Internet users"]
    if len(early) != 15 or early.isna().any():
        raise ValueError("technology adoption: early 1990-2004 internet history is incomplete")


def validate_treasuries(frame: pd.DataFrame, name: str) -> None:
    if frame.empty or frame["entity"].isna().any() or frame["entity"].duplicated().any():
        raise ValueError(f"{name}: missing or duplicate entities")
    if frame["entity"].str.strip().str.rstrip(":").str.lower().eq("total").any():
        raise ValueError(f"{name}: footer total row is present")
    if not np.isfinite(frame["btc"]).all() or frame["btc"].lt(0).any():
        raise ValueError(f"{name}: holdings must be non-negative")
    if "jurisdiction" in frame and not frame["jurisdiction"].isin(JURISDICTIONS).all():
        raise ValueError(f"{name}: jurisdiction must be one of {sorted(JURISDICTIONS)}")
