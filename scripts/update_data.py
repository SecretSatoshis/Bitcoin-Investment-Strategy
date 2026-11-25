#!/usr/bin/env python3
"""Fetch, check and write the daily data releases: the savings data and the supply and
demand release, both from a single download of one Report Library release."""
from __future__ import annotations

import argparse
import time

import pandas as pd

from bitcoin_investment_strategy.config import last_completed_utc
from bitcoin_investment_strategy.fetchers.report_library import ReleaseNotReady, fetch_raw_release
from bitcoin_investment_strategy.pipeline import update_data
from bitcoin_investment_strategy.research.config import ETF_FILES
from bitcoin_investment_strategy.research.pipeline import update_research_data

RETRY_SECONDS = 600


def _parse_as_of(value: str | None) -> tuple[pd.Timestamp, bool]:
    if not value:
        return last_completed_utc(), False
    parsed = pd.Timestamp(value)
    if pd.isna(parsed) or parsed.tz is not None or parsed != parsed.normalize():
        raise ValueError(f"--as-of must be a YYYY-MM-DD calendar date; got {value!r}")
    if parsed > last_completed_utc():
        raise ValueError(f"--as-of ({parsed.date()}) must be on or before the last completed UTC day")
    return parsed, True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-minutes", type=float, default=0,
                        help="How long to wait for the Report Library to publish the day")
    parser.add_argument("--as-of", type=str, default=None,
                        help="Optional YYYY-MM-DD backfill cutoff date (slices a newer Report Library release)")
    arguments = parser.parse_args()
    as_of, allow_slice = _parse_as_of(arguments.as_of)
    deadline = time.monotonic() + arguments.wait_minutes * 60
    while True:
        try:
            # Download and SHA-256 verify the Report Library release once for both pipelines.
            raw_release = fetch_raw_release(as_of, ETF_FILES, allow_slice=allow_slice)
            manifest = update_data(as_of=as_of, allow_slice=allow_slice, release=raw_release)
            update_research_data(
                pd.Timestamp(manifest["core_data_end"]),
                allow_slice=allow_slice,
                release=raw_release,
            )
            return
        except ReleaseNotReady as error:
            if time.monotonic() + RETRY_SECONDS > deadline:
                raise
            print(f"Waiting for the Report Library: {error}; retrying in {RETRY_SECONDS // 60} minutes")
            time.sleep(RETRY_SECONDS)


if __name__ == "__main__":
    main()
