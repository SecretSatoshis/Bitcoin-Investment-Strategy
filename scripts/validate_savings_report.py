#!/usr/bin/env python3
"""Validate the latest public savings bundle against this checkout's release."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bitcoin_investment_strategy.savings_report import validate_report_bundle

if __name__ == "__main__":
    manifest = validate_report_bundle(ROOT / "outputs/savings/latest", root=ROOT, require_latest=True)
    print(f"Validated savings report through {manifest['report_date']} ({manifest['snapshot_status']})")
