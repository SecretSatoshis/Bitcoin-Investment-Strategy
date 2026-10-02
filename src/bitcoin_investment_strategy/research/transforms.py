"""Build the supply and demand tables from the Report Library release, and the treasury tables
from CoinGecko's snapshots."""
from __future__ import annotations

import pandas as pd

from ..fetchers.report_library import annual_series

from .config import FLOW_SERIES, GENESIS_DATE, REPORT_LIBRARY_SERIES, UNDER_AGE_SUPPLY

MAX_EFFICIENCY_CARRY_DAYS = 365


def build_bitcoin_daily(release: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """The research daily table from the release's master-file columns.

    Supply older than 2-10 years is total supply less the younger supply, and each daily
    flow is the difference of its running total, so every block counts once. Mining
    efficiency is Coin Metrics' monthly estimate as the release carries it forward,
    refused once the newest estimate is more than a year old.
    """
    release = release.loc[:as_of]
    daily = release[list(REPORT_LIBRARY_SERIES)].rename(columns=REPORT_LIBRARY_SERIES)
    daily.index.name = "date"
    for over, under in UNDER_AGE_SUPPLY.items():
        # Publication rounding can leave a hundredth of a coin below zero before a cohort exists.
        daily[over] = (release["supply"] - release[under]).clip(lower=0)
    for flow, cumulative in FLOW_SERIES.items():
        daily[cumulative] = release[cumulative]
        daily[flow] = release[cumulative].diff()
    daily["market_cap_usd"] = daily["price"] * daily["supply"]
    daily["days_since_genesis"] = (daily.index - GENESIS_DATE).days.astype(float)

    observed = pd.to_datetime(release["cm_efficiency_source_date"]).dropna()
    if observed.empty or (as_of - observed.iloc[-1]).days > MAX_EFFICIENCY_CARRY_DAYS:
        raise ValueError("Efficiency has no observation within one year of cutoff")
    return daily


def build_technology_adoption(annual: pd.DataFrame) -> pd.DataFrame:
    """World internet users and population by year.

    Users are the World Bank's share of population times population from 2005, and Our
    World in Data's counts for 1990-2004. Population carries forward into a year the
    World Bank has not yet published.
    """
    share = annual_series(annual, "world_internet_users_pct")
    early = annual_series(annual, "world_internet_users")
    population = annual_series(annual, "world_population")
    years = population.index.union(share.index).union(early.index)
    population = population.reindex(years).ffill()
    users = (share.reindex(years) / 100.0 * population).combine_first(early.reindex(years))
    result = pd.DataFrame({"Year": years.astype(int), "Internet users": users.to_numpy(),
                           "global_population": population.to_numpy()})
    return result.dropna(how="all", subset=["Internet users", "global_population"]).reset_index(drop=True)


def build_owner_estimates(annual: pd.DataFrame) -> pd.DataFrame:
    """Crypto.com's yearly bitcoin-owner estimates, each with its report and basis."""
    rows = annual[annual["series"] == "bitcoin_owners_millions"]
    if rows.empty:
        raise ValueError("the release has no bitcoin-owner estimates")
    return pd.DataFrame({"year": rows["year"].astype(int), "bitcoin_owners_millions": rows["value"],
                         "source": rows["source"], "basis": rows["note"],
                         "source_url": rows["source_url"]}).sort_values("year").reset_index(drop=True)


def build_company_treasuries(frame: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    columns = [column for column in ("entity", "ticker", "country", "btc", "cost_basis_usd",
                                     "current_value_usd", "pct_of_supply") if column in frame.columns]
    result = frame[columns].copy()
    result["as_of"] = as_of.date().isoformat()
    result["source"] = "CoinGecko public treasury API"
    return result.sort_values("btc", ascending=False).reset_index(drop=True)


def build_government_treasuries(frame: pd.DataFrame, classifications: pd.DataFrame,
                                as_of: pd.Timestamp) -> pd.DataFrame:
    columns = [column for column in ("entity", "country", "btc", "current_value_usd", "pct_of_supply") if column in frame]
    result = frame[columns].copy()
    result = result.merge(classifications, on="entity", how="left", validate="one_to_one")
    # Entities missing from the reviewed table stay visible as unreviewed national listings.
    result["acquisition_type"] = result["acquisition_type"].fillna("unclassified")
    result["jurisdiction"] = result["jurisdiction"].fillna("national")
    result["category"] = "government"
    result["usd_millions"] = result.get("current_value_usd", pd.Series(index=result.index, dtype=float)) / 1e6
    result["pct_of_21m"] = result["btc"] / 21_000_000 * 100
    result["as_of"] = as_of.date().isoformat()
    result["evidence_tier"] = result["evidence_tier"].fillna("published_api_listing")
    result["source"] = "CoinGecko public treasury API; classifications are repository references"
    ordered = ["entity", "category", "jurisdiction", "btc", "usd_millions", "pct_of_21m",
               "acquisition_type", "as_of", "evidence_tier", "source"]
    return result[ordered].sort_values("btc", ascending=False).reset_index(drop=True)
