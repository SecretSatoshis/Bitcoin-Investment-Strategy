from __future__ import annotations

import pandas as pd

from .config import BRK_SERIES, FLOW_SERIES, KNOWN_NO_BLOCK_DATES, START_DATE


def nonoverlapping_daily(cumulative: pd.Series) -> pd.Series:
    """Convert cumulative daily snapshots to disjoint calendar-day flows."""
    flow = cumulative.diff()
    restarts = cumulative.notna() & cumulative.shift(1).isna()
    previous_valid = cumulative.ffill().shift(1)
    flow.loc[restarts] = cumulative.loc[restarts] - previous_valid.loc[restarts]
    first = cumulative.first_valid_index()
    if first is not None and first == cumulative.index[0]:
        flow.loc[first] = cumulative.loc[first]
    return flow


def build_bitcoin_daily(raw_brk: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timestamp]:
    missing = set(BRK_SERIES).difference(raw_brk.columns)
    if missing:
        raise ValueError(f"BRK input is missing required series: {sorted(missing)}")
    last_valid = {column: raw_brk[column].last_valid_index() for column in BRK_SERIES}
    empty = [column for column, ending in last_valid.items() if ending is None]
    if empty:
        raise ValueError(f"BRK input has all-null required series: {empty}")
    core_end = min(last_valid.values())
    raw_brk = raw_brk.loc[:core_end, list(BRK_SERIES)].copy()
    daily = raw_brk.rename(columns=BRK_SERIES).copy()

    for daily_name, cumulative_name in FLOW_SERIES.items():
        daily[daily_name] = nonoverlapping_daily(daily[cumulative_name])

    daily["market_cap_usd"] = daily["price"] * daily["supply"]
    genesis = pd.Timestamp(START_DATE)
    daily["days_since_genesis"] = (daily.index - genesis).days.astype(float)
    daily["years_since_genesis"] = daily["days_since_genesis"] / 365.25
    daily.index.name = "date"
    return daily, core_end
