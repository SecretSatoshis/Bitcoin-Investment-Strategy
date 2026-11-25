"""Copy a verified build into the checkout: exactly the allowlisted public files, nothing else.

Runs in the publish job with the system Python, so it uses only the standard library.
Committed notebooks remain stripped of outputs in Git; executed notebook artifacts are
verified for data freshness before publishing data and savings reports.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bitcoin_investment_strategy.release_files import (  # noqa: E402
    DATA_FILES, DATA_MANIFEST, EXECUTED_MANDATORY_NOTEBOOKS, EXECUTED_NOTEBOOKS, NOTEBOOKS,
    PUBLICATION_FILES, REPORT_DIR, REPORT_FILES, REPORT_MANIFEST, RESEARCH_FILES, RESEARCH_MANIFEST,
)

# Match the release/cutoff date printed by any of the three executed notebooks.
NOTEBOOK_RELEASE = re.compile(
    r"(?:Data release:|Data cutoff:|Release)\s+(\d{4}-\d{2}-\d{2})"
    r"|^\s*release\s+(\d{4}-\d{2}-\d{2})",
    re.MULTILINE,
)


def notebook_data_end(path):
    """Data date printed by an executed notebook, or None if it cannot be read."""
    try:
        notebook = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for cell in notebook.get("cells", []):
        for output in cell.get("outputs", []):
            text = output.get("text", "")
            joined = "".join(text) if isinstance(text, list) else str(text)
            match = NOTEBOOK_RELEASE.search(joined)
            if match:
                return match.group(1) or match.group(2)
    return None


def is_notebook_stripped(path):
    """Return True iff every code cell has empty outputs and null execution_count."""
    notebook = json.loads(Path(path).read_text(encoding="utf-8"))
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") == "code":
            if cell.get("outputs"):
                return False
            if cell.get("execution_count") is not None:
                return False
    return True


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _already_current(root, data, research, report):
    """True when committed manifests and report provenance already match this exact release."""
    try:
        prev_data = json.loads((root / DATA_MANIFEST).read_text(encoding="utf-8"))
        prev_research = json.loads((root / RESEARCH_MANIFEST).read_text(encoding="utf-8"))
        prev_report = json.loads((root / REPORT_DIR / REPORT_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if (
        prev_data.get("core_data_end") != data["core_data_end"]
        or prev_data.get("release_id") != data["release_id"]
        or prev_research.get("core_data_end") != research["core_data_end"]
        or prev_research.get("release_id") != research["release_id"]
    ):
        return False
    prev_prov = prev_report.get("provenance", {})
    cand_prov = report.get("provenance", {})
    stable_keys = ("source_release_id", "source_data_end", "price_sha256", "engine_sha256", "exporter_sha256")
    return all(prev_prov.get(k) == cand_prov.get(k) for k in stable_keys)


def restore(source, root=ROOT):
    source, root = Path(source), Path(root)
    found = set()
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("Publication payload cannot contain symlinks")
        if path.is_file():
            found.add(path.relative_to(source).as_posix())
    executed_found = found & EXECUTED_NOTEBOOKS
    non_executed_found = found - EXECUTED_NOTEBOOKS
    if non_executed_found != PUBLICATION_FILES:
        raise ValueError(f"Publication payload differs from allowlist: {non_executed_found ^ PUBLICATION_FILES}")
    missing_mandatory = EXECUTED_MANDATORY_NOTEBOOKS - executed_found
    if missing_mandatory:
        raise ValueError(f"Publication payload is missing mandatory executed notebooks: {sorted(missing_mandatory)}")

    data = json.loads((source / DATA_MANIFEST).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or set(data.get("artifacts", {})) != DATA_FILES:
        raise ValueError("Incomplete data manifest")
    for name, metadata in data["artifacts"].items():
        if digest(source / name) != metadata["sha256"]:
            raise ValueError(f"Data checksum mismatch: {name}")
    report_root = source / REPORT_DIR
    report = json.loads((report_root / REPORT_MANIFEST).read_text(encoding="utf-8"))
    if report.get("schema_version") != 1 or set(report.get("files", {})) != REPORT_FILES:
        raise ValueError("Incomplete savings manifest")
    for name, metadata in report["files"].items():
        if digest(report_root / name) != metadata["sha256"]:
            raise ValueError(f"Savings checksum mismatch: {name}")
    if report["report_date"] != data["core_data_end"]:
        raise ValueError("Savings and data report dates disagree")
    research = json.loads((source / RESEARCH_MANIFEST).read_text(encoding="utf-8"))
    if research.get("schema_version") != 1 or set(research.get("artifacts", {})) != RESEARCH_FILES:
        raise ValueError("Incomplete supply and demand manifest")
    for name, metadata in research["artifacts"].items():
        if digest(source / name) != metadata["sha256"]:
            raise ValueError(f"Data checksum mismatch: {name}")
    if research["core_data_end"] != data["core_data_end"]:
        raise ValueError("Supply and demand release and savings data dates disagree")
    previous = json.loads((root / DATA_MANIFEST).read_text(encoding="utf-8"))
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

    # Verify freshness for every executed notebook in the build artifact.
    for nb_rel in sorted(executed_found):
        reported_end = notebook_data_end(source / nb_rel)
        if reported_end != data["core_data_end"]:
            raise ValueError(
                f"Executed notebook {nb_rel} reports {reported_end!r}, "
                f"does not report this data release ({data['core_data_end']})"
            )

    # Ensure committed notebooks in the checkout remain stripped of outputs.
    for nb_rel in sorted(NOTEBOOKS):
        committed_nb = root / nb_rel
        if committed_nb.is_file() and not is_notebook_stripped(committed_nb):
            raise ValueError(f"Committed notebook {nb_rel} contains outputs; strip before publishing")

    if _already_current(root, data, research, report):
        print(f"Published snapshot for {data['core_data_end']} is already current; skipping redundant restore.")
        return data["core_data_end"]

    for name in sorted(PUBLICATION_FILES):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    print(f"Verified {len(executed_found)} executed notebooks (committed notebooks remain stripped).")
    return data["core_data_end"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(f"Restored verified publication through {restore(args.source)}")
