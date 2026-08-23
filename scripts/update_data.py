#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bitcoin_investment_strategy.pipeline import update_data  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the shared notebook data release")
    parser.add_argument("--as-of", help="Last completed UTC date to request (YYYY-MM-DD)")
    arguments = parser.parse_args()
    as_of = pd.Timestamp(arguments.as_of) if arguments.as_of else None
    update_data(as_of)


if __name__ == "__main__":
    main()
