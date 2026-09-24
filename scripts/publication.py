"""Exact public payload; never copy whole local data or notebook directories."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = {
    "data/raw/brk/brk_daily.csv", "data/raw/fred/median_household_income.csv",
    "data/processed/bitcoin_daily.csv", "data/processed/median_household_income_annual.csv",
    "data/manifests/source_registry.csv", "data/manifests/column_dictionary.csv",
}
REPORT_NAMES = {
    "plan_definition.json", "section3_packet.json", "README.md",
    "cohort_summary.csv", "ytd_summary.csv", "benchmark_results.csv",
    "cohort_paths.csv", "contribution_schedule.csv",
    "current_year_savings.png", "cohort_accumulation.png", "ytd_gains_vs_cash.png",
}
PUBLICATION_FILES = DATA_FILES | {
    "data/manifests/data_manifest.json", "notebooks/bitcoin_savings_plan.ipynb",
    *{f"outputs/savings/latest/{name}" for name in REPORT_NAMES | {"export_manifest.json"}},
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restore(source, root=ROOT):
    source, root = Path(source), Path(root)
    found = set()
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("Publication payload cannot contain symlinks")
        if path.is_file():
            found.add(path.relative_to(source).as_posix())
    if found != PUBLICATION_FILES:
        raise ValueError(f"Publication payload differs from allowlist: {found ^ PUBLICATION_FILES}")
    data = json.loads((source / "data/manifests/data_manifest.json").read_text())
    if data.get("schema_version") != 1 or set(data.get("artifacts", {})) != DATA_FILES:
        raise ValueError("Incomplete data manifest")
    for name, metadata in data["artifacts"].items():
        if digest(source / name) != metadata["sha256"]:
            raise ValueError(f"Data checksum mismatch: {name}")
    report_root = source / "outputs/savings/latest"
    report = json.loads((report_root / "export_manifest.json").read_text())
    if report.get("schema_version") != 1 or set(report.get("files", {})) != REPORT_NAMES:
        raise ValueError("Incomplete savings manifest")
    for name, metadata in report["files"].items():
        if digest(report_root / name) != metadata["sha256"]:
            raise ValueError(f"Savings checksum mismatch: {name}")
    if report["report_date"] != data["core_data_end"]:
        raise ValueError("Savings and data report dates disagree")
    previous = json.loads((root / "data/manifests/data_manifest.json").read_text())
    if data["core_data_end"] < previous["core_data_end"]:
        raise ValueError("Refusing to replace a newer data release")
    provenance = report["provenance"]
    expected = {
        "source_release_id": data["release_id"], "source_data_end": data["core_data_end"],
        "price_file": "data/processed/bitcoin_daily.csv",
        "price_sha256": digest(source / "data/processed/bitcoin_daily.csv"),
        "source_manifest_sha256": digest(source / "data/manifests/data_manifest.json"),
        "engine_sha256": digest(root / "src/bitcoin_investment_strategy/savings.py"),
        "exporter_sha256": digest(root / "src/bitcoin_investment_strategy/savings_report.py"),
    }
    if provenance != expected:
        raise ValueError("Publication provenance disagrees with source data or checked-out code")
    for name in sorted(PUBLICATION_FILES):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    return data["core_data_end"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(f"Restored verified publication through {restore(args.source)}")
