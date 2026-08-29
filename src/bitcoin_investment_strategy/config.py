from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MANIFEST_DIR = DATA_DIR / "manifests"

START_DATE = "2009-01-03"
BRK_BASE_URL = "https://bitview.space/api"
FRED_MEDIAN_INCOME_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MEHOINUSA646N"

# MEHOINUSA646N is annual and published with roughly a one-year lag, so the newest year
# in a healthy cache is normally the prior year. Three years allows for that lag plus a
# late release; beyond it the committed fallback is a frozen figure being presented as
# current, which every other stale-data path in this project refuses to do.
FRED_CACHE_MAX_AGE_YEARS = 3

COHORTS = ("1y", "2y", "3y", "4y", "5y", "10y")

# One upstream request per metric. Values are canonical column names in the
# shared daily table. price_close is the one price request used by all notebooks.
BRK_SERIES = OrderedDict(
    [
        ("price_close", "price"),
        ("supply", "supply"),
        ("subsidy_cumulative", "subsidy_cumulative"),
        ("fees_cumulative", "fees_cumulative"),
        ("realized_cap", "realized_cap"),
        ("realized_price", "realized_price"),
        ("mvrv", "mvrv"),
        ("supply_in_profit", "supply_in_profit"),
        ("coindays_destroyed_cumulative", "coindays_destroyed_cumulative"),
        ("lth_supply", "lth_supply"),
        ("sth_supply", "sth_supply"),
        ("lth_transfer_volume_cumulative", "lth_transfer_volume_cumulative"),
        ("lth_realized_price", "lth_realized_price"),
        ("sth_realized_price", "sth_realized_price"),
        ("lth_realized_profit_cumulative", "lth_realized_profit_cumulative"),
        ("lth_realized_loss_cumulative", "lth_realized_loss_cumulative"),
        ("sth_realized_profit_cumulative", "sth_realized_profit_cumulative"),
        ("sth_realized_loss_cumulative", "sth_realized_loss_cumulative"),
        ("hash_rate", "hash_rate"),
        ("difficulty", "difficulty"),
        ("subsidy_average_24h", "block_subsidy_btc"),
        ("addr_count", "non_zero_addr_count"),
        ("addrs_over_100k_sats_addr_count", "addr_count_over_0p001_btc"),
        ("addrs_over_1m_sats_addr_count", "addr_count_over_0p01_btc"),
        ("addrs_over_10m_sats_addr_count", "addr_count_over_0p1_btc"),
    ]
)

for _age in COHORTS:
    BRK_SERIES[f"utxos_over_{_age}_old_supply"] = f"utxos_over_{_age}_old_supply"
    BRK_SERIES[
        f"utxos_over_{_age}_old_transfer_volume_cumulative"
    ] = f"utxos_over_{_age}_old_transfer_volume_cumulative"

FLOW_SERIES = OrderedDict(
    [
        ("subsidy_daily", "subsidy_cumulative"),
        ("fees_daily", "fees_cumulative"),
        ("coindays_destroyed_daily", "coindays_destroyed_cumulative"),
        ("lth_transfer_volume_daily", "lth_transfer_volume_cumulative"),
        ("lth_realized_profit_daily", "lth_realized_profit_cumulative"),
        ("lth_realized_loss_daily", "lth_realized_loss_cumulative"),
        ("sth_realized_profit_daily", "sth_realized_profit_cumulative"),
        ("sth_realized_loss_daily", "sth_realized_loss_cumulative"),
    ]
)
for _age in COHORTS:
    FLOW_SERIES[
        f"utxos_over_{_age}_old_transfer_volume_daily"
    ] = f"utxos_over_{_age}_old_transfer_volume_cumulative"

KNOWN_NO_BLOCK_DATES = pd.date_range("2009-01-04", "2009-01-08", freq="D")


def last_completed_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)


def ensure_directories() -> None:
    for path in (RAW_DIR, PROCESSED_DIR, MANIFEST_DIR):
        path.mkdir(parents=True, exist_ok=True)
