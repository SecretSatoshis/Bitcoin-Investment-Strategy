import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from bitcoin_investment_strategy.config import ROOT
from bitcoin_investment_strategy.savings_report import (
    REPORT_FILES, export_report, validate_report_bundle,
)

spec = importlib.util.spec_from_file_location("publication", ROOT / "scripts/publication.py")
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


def _fake_executed_notebook(release_date: str, label: str = "Data release") -> str:
    return json.dumps({
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [{
            "cell_type": "code",
            "execution_count": 1,
            "metadata": {},
            "source": [],
            "outputs": [{"output_type": "stream", "name": "stdout", "text": [f"{label}: {release_date}-abc123\n"]}],
        }],
    })


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.golden = Path(cls.temp.name) / "golden"
        export_report(ROOT, output_dir=cls.golden)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.temp_case = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_case.cleanup)
        self.base = Path(self.temp_case.name)
        self.bundle = self.base / "bundle"
        shutil.copytree(self.golden, self.bundle)

    def payload(self, *, include_demand: bool = True, notebook_dates: dict[str, str] | None = None):
        source, target = self.base / "source", self.base / "target"
        for name in publication.PUBLICATION_FILES:
            original = (self.golden / Path(name).name
                        if name.startswith("outputs/savings/latest/") else ROOT / name)
            dest = source / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, dest)
        release_end = json.loads((source / "data/manifests/data_manifest.json").read_text())["core_data_end"]
        dates = notebook_dates or {}
        nb_specs = [
            ("build/executed-notebooks/bitcoin_savings_plan.ipynb", "Data release"),
            ("build/executed-notebooks/bitcoin_supply_dynamics.ipynb", "Release"),
        ]
        if include_demand:
            nb_specs.append(("build/executed-notebooks/bitcoin_demand_dynamics.ipynb", "Data cutoff"))
        for rel, label in nb_specs:
            dest = source / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            d = dates.get(rel, release_end)
            prefix = f"{label} {d}-abc123\n" if label == "Release" else f"{label}: {d}\n"
            dest.write_text(json.dumps({
                "cells": [{"cell_type": "code", "execution_count": 1, "outputs": [
                    {"output_type": "stream", "text": [prefix]}
                ]}]
            }))
        for name in ["data/manifests/data_manifest.json",
                     "src/bitcoin_investment_strategy/savings.py",
                     "src/bitcoin_investment_strategy/savings_report.py",
                     *sorted(publication.NOTEBOOKS)]:
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, dest)
        return source, target

    def test_complete_report_matches_source_release_and_accounting(self):
        manifest = validate_report_bundle(self.bundle, root=ROOT, require_latest=True)
        source = json.loads((ROOT / "data/manifests/data_manifest.json").read_text())
        self.assertEqual(manifest["report_date"], source["core_data_end"])
        self.assertEqual(REPORT_FILES, publication.REPORT_FILES)

    def test_export_report_is_idempotent_on_unchanged_inputs(self):
        first = json.loads((self.bundle / "export_manifest.json").read_text())
        export_report(ROOT, output_dir=self.bundle)
        second = json.loads((self.bundle / "export_manifest.json").read_text())
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(first, second)

    def test_missing_and_modified_files_fail(self):
        path = self.bundle / "cohort_summary.csv"
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            validate_report_bundle(self.bundle, root=ROOT)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            validate_report_bundle(self.bundle, root=ROOT)

    def test_mixed_source_manifest_fails(self):
        name = self.bundle / "export_manifest.json"
        manifest = json.loads(name.read_text())
        manifest["provenance"]["source_release_id"] = "other-release"
        name.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "provenance"):
            validate_report_bundle(self.bundle, root=ROOT)

    def test_interim_snapshot_cannot_claim_quarter_end(self):
        name = self.bundle / "export_manifest.json"
        manifest = json.loads(name.read_text())
        manifest["snapshot_status"] = ("interim" if manifest["snapshot_status"] == "quarter_end" else "quarter_end")
        name.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "quarter-end"):
            validate_report_bundle(self.bundle, root=ROOT)

    def test_verified_payload_restores_public_files_and_keeps_notebooks_stripped(self):
        source, target = self.payload()
        publication.restore(source, target)
        for name in publication.PUBLICATION_FILES:
            self.assertEqual((source / name).read_bytes(), (target / name).read_bytes())
        for nb_rel in publication.NOTEBOOKS:
            self.assertTrue(publication.is_notebook_stripped(target / nb_rel))

    def test_optional_demand_notebook_can_be_absent_but_supply_is_mandatory(self):
        source, target = self.payload(include_demand=False)
        publication.restore(source, target)
        (source / "build/executed-notebooks/bitcoin_supply_dynamics.ipynb").unlink()
        with self.assertRaisesRegex(ValueError, "mandatory executed notebooks"):
            publication.restore(source, target)

    def test_stale_executed_notebook_is_rejected_for_all_notebooks(self):
        for nb_rel in (
            "build/executed-notebooks/bitcoin_savings_plan.ipynb",
            "build/executed-notebooks/bitcoin_supply_dynamics.ipynb",
            "build/executed-notebooks/bitcoin_demand_dynamics.ipynb",
        ):
            with self.subTest(notebook=nb_rel):
                source, target = self.payload(notebook_dates={nb_rel: "2000-01-01"})
                with self.assertRaisesRegex(ValueError, "does not report this data release"):
                    publication.restore(source, target)

    def test_restore_short_circuits_idempotently_when_already_current(self):
        source, target = self.payload()
        publication.restore(source, target)
        # Mutating retrieved_at_utc alone in source while release_id & code hashes match
        # should NOT overwrite target's committed data_manifest.json.
        target_manifest_before = (target / "data/manifests/data_manifest.json").read_bytes()
        src_manifest_path = source / "data/manifests/data_manifest.json"
        src_manifest = json.loads(src_manifest_path.read_text())
        src_manifest["retrieved_at_utc"] = "2099-01-01T00:00:00+00:00"
        src_manifest_path.write_text(json.dumps(src_manifest, indent=2) + "\n")
        # Update report provenance source_manifest_sha256 to match the new source manifest
        rep_path = source / "outputs/savings/latest/export_manifest.json"
        rep = json.loads(rep_path.read_text())
        rep["provenance"]["source_manifest_sha256"] = publication.digest(src_manifest_path)
        rep_path.write_text(json.dumps(rep, indent=2) + "\n")
        publication.restore(source, target)
        self.assertEqual((target / "data/manifests/data_manifest.json").read_bytes(), target_manifest_before)

    def test_unlisted_file_in_payload_is_rejected_before_copy(self):
        source, target = self.payload()
        (source / "notebooks").mkdir(parents=True, exist_ok=True)
        (source / "notebooks/other.ipynb").write_text("not part of the release")
        with self.assertRaisesRegex(ValueError, "allowlist"):
            publication.restore(source, target)
        self.assertFalse((target / "outputs").exists())

    def test_corrupt_payload_is_rejected_before_copy(self):
        source, target = self.payload()
        (source / "data/processed/bitcoin_daily.csv").write_text("bad data")
        with self.assertRaisesRegex(ValueError, "checksum"):
            publication.restore(source, target)
        self.assertFalse((target / "outputs").exists())

    def test_publication_refuses_to_roll_back_newer_data(self):
        source, target = self.payload()
        name = target / "data/manifests/data_manifest.json"
        manifest = json.loads(name.read_text())
        manifest["core_data_end"] = "9999-12-31"
        name.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "newer"):
            publication.restore(source, target)


if __name__ == "__main__":
    unittest.main()
