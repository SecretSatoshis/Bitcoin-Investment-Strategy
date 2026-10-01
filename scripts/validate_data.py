#!/usr/bin/env python3
"""Check the data release in this checkout against its manifest."""
from __future__ import annotations

import pandas as pd

from bitcoin_investment_strategy.config import ROOT
from bitcoin_investment_strategy.release_files import DATA_MANIFEST
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


if __name__ == "__main__":
    main()
