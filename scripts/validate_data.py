#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bitcoin_investment_strategy.validation import (  # noqa: E402
    validate_bitcoin_daily,
    validate_release_manifest,
)


def main() -> None:
    manifest = validate_release_manifest(ROOT / "data/manifests/data_manifest.json")
    daily = pd.read_csv(ROOT / "data/processed/bitcoin_daily.csv", parse_dates=["date"]).set_index("date")
    validate_bitcoin_daily(daily)
    income = pd.read_csv(ROOT / "data/processed/median_household_income_annual.csv")
    if income["Year"].duplicated().any() or income["median_household_income_usd"].le(0).any():
        raise SystemExit("median household income failed annual uniqueness or positivity checks")
    print(f"Validated release {manifest['release_id']} ({len(manifest['artifacts'])} artifacts)")


if __name__ == "__main__":
    main()
