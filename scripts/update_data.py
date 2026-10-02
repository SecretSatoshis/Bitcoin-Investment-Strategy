#!/usr/bin/env python3
"""Fetch, check and write the daily data releases: the savings data and the supply and
demand release, both from the same Report Library release."""
from __future__ import annotations

import argparse
import time

import pandas as pd

from bitcoin_investment_strategy.fetchers.report_library import ReleaseNotReady
from bitcoin_investment_strategy.pipeline import update_data
from bitcoin_investment_strategy.research.pipeline import update_research_data

RETRY_SECONDS = 600


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-minutes", type=float, default=0,
                        help="How long to wait for the Report Library to publish the day")
    arguments = parser.parse_args()
    deadline = time.monotonic() + arguments.wait_minutes * 60
    while True:
        try:
            manifest = update_data()
            update_research_data(pd.Timestamp(manifest["core_data_end"]))
            return
        except ReleaseNotReady as error:
            if time.monotonic() + RETRY_SECONDS > deadline:
                raise
            print(f"Waiting for the Report Library: {error}; retrying in {RETRY_SECONDS // 60} minutes")
            time.sleep(RETRY_SECONDS)


if __name__ == "__main__":
    main()
