"""Copy a verified build into the checkout: exactly the allowlisted public files, nothing else.

Runs in the publish job with the system Python, so it uses only the standard library.
"""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bitcoin_investment_strategy.release_files import (  # noqa: E402
    DATA_FILES, DATA_MANIFEST, NOTEBOOK, NOTEBOOKS, PUBLICATION_FILES, REPORT_DIR, REPORT_FILES, REPORT_MANIFEST,
    RESEARCH_FILES, RESEARCH_MANIFEST,
)

# The executed notebooks embed chart images that change every day. Data and the savings
# report still publish daily; the notebooks are committed weekly — for data through a
# Sunday — or whenever the committed savings notebook has fallen a week behind.
NOTEBOOK_REFRESH_DAYS = 7
NOTEBOOK_RELEASE = re.compile(r"Data release: (\d{4}-\d{2}-\d{2})")


def notebook_data_end(path):
    """Data date printed by an executed notebook, or None if it cannot be read."""
    try:
        notebook = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    for cell in notebook.get("cells", []):
        for output in cell.get("outputs", []):
            match = NOTEBOOK_RELEASE.search("".join(output.get("text", "")))
            if match:
                return match.group(1)
    return None


def notebook_due(data_end, committed_notebook):
    end = date.fromisoformat(data_end)
    if end.weekday() == 6:
        return True
    previous = notebook_data_end(committed_notebook)
    return previous is None or (end - date.fromisoformat(previous)).days >= NOTEBOOK_REFRESH_DAYS


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
    data = json.loads((source / DATA_MANIFEST).read_text())
    if data.get("schema_version") != 1 or set(data.get("artifacts", {})) != DATA_FILES:
        raise ValueError("Incomplete data manifest")
    for name, metadata in data["artifacts"].items():
        if digest(source / name) != metadata["sha256"]:
            raise ValueError(f"Data checksum mismatch: {name}")
    report_root = source / REPORT_DIR
    report = json.loads((report_root / REPORT_MANIFEST).read_text())
    if report.get("schema_version") != 1 or set(report.get("files", {})) != REPORT_FILES:
        raise ValueError("Incomplete savings manifest")
    for name, metadata in report["files"].items():
        if digest(report_root / name) != metadata["sha256"]:
            raise ValueError(f"Savings checksum mismatch: {name}")
    if report["report_date"] != data["core_data_end"]:
        raise ValueError("Savings and data report dates disagree")
    research = json.loads((source / RESEARCH_MANIFEST).read_text())
    if research.get("schema_version") != 1 or set(research.get("artifacts", {})) != RESEARCH_FILES:
        raise ValueError("Incomplete supply and demand manifest")
    for name, metadata in research["artifacts"].items():
        if digest(source / name) != metadata["sha256"]:
            raise ValueError(f"Data checksum mismatch: {name}")
    if research["core_data_end"] != data["core_data_end"]:
        raise ValueError("Supply and demand release and savings data dates disagree")
    previous = json.loads((root / DATA_MANIFEST).read_text())
    if data["core_data_end"] < previous["core_data_end"]:
        raise ValueError("Refusing to replace a newer data release")
    provenance = report["provenance"]
    expected = {
        "source_release_id": data["release_id"], "source_data_end": data["core_data_end"],
        "price_file": "data/processed/bitcoin_daily.csv",
        "price_sha256": digest(source / "data/processed/bitcoin_daily.csv"),
        "source_manifest_sha256": digest(source / DATA_MANIFEST),
        "engine_sha256": digest(root / "src/bitcoin_investment_strategy/savings.py"),
        "exporter_sha256": digest(root / "src/bitcoin_investment_strategy/savings_report.py"),
    }
    if provenance != expected:
        raise ValueError("Publication provenance disagrees with source data or checked-out code")
    if notebook_data_end(source / NOTEBOOK) != data["core_data_end"]:
        raise ValueError("Executed notebook does not report this data release")
    include_notebooks = notebook_due(data["core_data_end"], root / NOTEBOOK)
    for name in sorted(PUBLICATION_FILES):
        if name in NOTEBOOKS and not include_notebooks:
            continue
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    print("Executed notebooks " + ("updated (weekly refresh)" if include_notebooks
                                   else "left at their last weekly refresh"))
    return data["core_data_end"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(f"Restored verified publication through {restore(args.source)}")
