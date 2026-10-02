"""Paths, sources and the Report Library columns the supply and demand release reads."""
from __future__ import annotations

import pandas as pd

from ..config import DATA_DIR

RESEARCH_DIR = DATA_DIR / "research"
MANIFEST_DIR = RESEARCH_DIR / "manifests"
RESEARCH_MANIFEST = MANIFEST_DIR / "data_manifest.json"
REFERENCE_DIR = DATA_DIR / "reference"

GENESIS_DATE = pd.Timestamp("2009-01-03")
# Halving dates (UTC day of blocks 210,000, 420,000, 630,000 and 840,000), the same
# schedule the Report Library uses. Add the next one when block 1,050,000 is mined.
HALVING_DATES = ("2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20")

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
# The Report Library's ETF tables, copied into this release from the same Report Library release.
ETF_FILES = ("etf_daily.csv", "etf_totals_daily.csv", "etf_quarterly.csv")

COHORTS = ("1y", "2y", "3y", "4y", "5y", "10y")

# Report Library master-file columns, mapped to their names in bitcoin_daily.csv.
REPORT_LIBRARY_SERIES = {
    "price_close": "price",
    "supply": "supply",
    "realized_cap": "realized_cap",
    "realized_price": "realized_price",
    "mvrv": "mvrv",
    "supply_in_profit": "supply_in_profit",
    "lth_supply": "lth_supply",
    "sth_supply": "sth_supply",
    "lth_realized_price": "lth_realized_price",
    "sth_realized_price": "sth_realized_price",
    "hash_rate": "hash_rate",
    "difficulty": "difficulty",
    "addr_count": "non_zero_addr_count",
    "addrs_over_100k_sats_addr_count": "addr_count_over_0p001_btc",
    "addrs_over_1m_sats_addr_count": "addr_count_over_0p01_btc",
    "addrs_over_10m_sats_addr_count": "addr_count_over_0p1_btc",
    "utxos_over_1y_old_supply": "utxos_over_1y_old_supply",
    "cm_efficiency_j_gh": "cm_efficiency_j_gh",
}
# The release has supply older than one year directly; older thresholds are total supply
# less the supply younger than them.
UNDER_AGE_SUPPLY = {f"utxos_over_{age}_old_supply": f"utxos_under_{age}_old_supply"
                    for age in COHORTS if age != "1y"}

# Daily flows, each the day-to-day difference of a running total in the release.
FLOW_SERIES = {
    "subsidy_daily": "subsidy_cumulative",
    "fees_daily": "fees_cumulative",
    "coindays_destroyed_daily": "coindays_destroyed_cumulative",
    "lth_realized_profit_daily": "lth_realized_profit_cumulative",
    "lth_realized_loss_daily": "lth_realized_loss_cumulative",
    "sth_realized_profit_daily": "sth_realized_profit_cumulative",
    "sth_realized_loss_daily": "sth_realized_loss_cumulative",
}
for _age in COHORTS:
    FLOW_SERIES[f"utxos_over_{_age}_old_transfer_volume_daily"] = (
        f"utxos_over_{_age}_old_transfer_volume_cumulative")

REPORT_LIBRARY_COLUMNS = [*REPORT_LIBRARY_SERIES, *UNDER_AGE_SUPPLY.values(), *FLOW_SERIES.values(),
                          "cm_efficiency_source_date"]
