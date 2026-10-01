#!/usr/bin/env python3
"""Check the published savings report against this checkout's data release and code."""
from bitcoin_investment_strategy.config import ROOT
from bitcoin_investment_strategy.release_files import REPORT_DIR
from bitcoin_investment_strategy.savings_report import validate_report_bundle


def main() -> None:
    manifest = validate_report_bundle(ROOT / REPORT_DIR, root=ROOT, require_latest=True)
    print(f"Validated savings report through {manifest['report_date']} ({manifest['snapshot_status']})")


if __name__ == "__main__":
    main()
