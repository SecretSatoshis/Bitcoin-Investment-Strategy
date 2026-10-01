#!/usr/bin/env python3
"""Fetch, check and write the daily data release."""
from __future__ import annotations

import argparse
import time

from bitcoin_investment_strategy.fetchers.report_library import ReleaseNotReady
from bitcoin_investment_strategy.pipeline import update_data

RETRY_SECONDS = 600


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-minutes", type=float, default=0,
                        help="How long to wait for the Report Library to publish the day")
    arguments = parser.parse_args()
    deadline = time.monotonic() + arguments.wait_minutes * 60
    while True:
        try:
            update_data()
            return
        except ReleaseNotReady as error:
            if time.monotonic() + RETRY_SECONDS > deadline:
                raise
            print(f"Waiting for the Report Library: {error}; retrying in {RETRY_SECONDS // 60} minutes")
            time.sleep(RETRY_SECONDS)


if __name__ == "__main__":
    main()
