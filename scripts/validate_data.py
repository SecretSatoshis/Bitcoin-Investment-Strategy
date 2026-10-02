#!/usr/bin/env python3
"""Check the savings data and the supply and demand release in this checkout against their manifests."""
from __future__ import annotations

import pandas as pd

from bitcoin_investment_strategy.config import ROOT
from bitcoin_investment_strategy.release_files import DATA_MANIFEST, RESEARCH_MANIFEST
from bitcoin_investment_strategy.research import validation as research
from bitcoin_investment_strategy.validation import (
    validate_bitcoin_daily,
    validate_income,
    validate_release_manifest,
)


def main() -> None:
    manifest = validate_release_manifest(ROOT / DATA_MANIFEST)
    daily = pd.read_csv(ROOT / "data/processed/bitcoin_daily.csv", parse_dates=["date"]).set_index("date")
    validate_bitcoin_daily(daily)
    income = pd.read_csv(ROOT / "data/processed/median_household_income_annual.csv")
    validate_income(income, pd.Timestamp(manifest["core_data_end"]))
    print(f"Validated release {manifest['release_id']} ({len(manifest['artifacts'])} artifacts)")

    research_manifest = research.validate_release_manifest(ROOT / RESEARCH_MANIFEST)
    if research_manifest["core_data_end"] != manifest["core_data_end"]:
        raise ValueError("The supply and demand release and the savings data cover different days")
    folder = ROOT / "data/research"
    research.validate_bitcoin_daily(pd.read_csv(folder / "bitcoin_daily.csv", parse_dates=["date"]).set_index("date"))
    research.validate_technology(pd.read_csv(folder / "technology_adoption_annual.csv"))
    research.validate_etf({name: pd.read_csv(folder / name, parse_dates=["date"])
                           for name in ("etf_daily.csv", "etf_totals_daily.csv")})
    print(f"Validated release {research_manifest['release_id']} ({len(research_manifest['artifacts'])} artifacts)")


if __name__ == "__main__":
    main()
