#!/usr/bin/env python3
"""Check the published savings report against this checkout's data release and code."""
from __future__ import annotations

import argparse
from pathlib import Path
import tempfile

from bitcoin_investment_strategy.config import ROOT
from bitcoin_investment_strategy.release_files import REPORT_DIR
from bitcoin_investment_strategy.savings_report import export_report, validate_report_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run-export",
        action="store_true",
        help="Rebuild and validate the savings report in a temp dir (used by PR validation)",
    )
    arguments = parser.parse_args()
    if arguments.dry_run_export:
        with tempfile.TemporaryDirectory(prefix="savings-report-pr-") as tmp:
            dest = Path(tmp) / "latest"
            export_report(ROOT, output_dir=dest)
            manifest = validate_report_bundle(dest, root=ROOT, require_latest=True)
    else:
        manifest = validate_report_bundle(ROOT / REPORT_DIR, root=ROOT, require_latest=True)
    print(f"Validated savings report through {manifest['report_date']} ({manifest['snapshot_status']})")


if __name__ == "__main__":
    main()
