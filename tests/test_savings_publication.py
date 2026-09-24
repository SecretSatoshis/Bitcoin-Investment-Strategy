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

    def payload(self):
        source, target = self.base / "source", self.base / "target"
        for name in publication.PUBLICATION_FILES:
            original = (self.golden / Path(name).name
                        if name.startswith("outputs/savings/latest/") else ROOT / name)
            dest = source / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, dest)
        for name in ["data/manifests/data_manifest.json",
                     "src/bitcoin_investment_strategy/savings.py",
                     "src/bitcoin_investment_strategy/savings_report.py"]:
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, dest)
        return source, target

    def test_complete_report_matches_source_release_and_accounting(self):
        manifest = validate_report_bundle(self.bundle, root=ROOT, require_latest=True)
        source = json.loads((ROOT / "data/manifests/data_manifest.json").read_text())
        self.assertEqual(manifest["report_date"], source["core_data_end"])
        self.assertEqual(REPORT_FILES, publication.REPORT_NAMES)

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

    def test_verified_payload_restores_only_exact_public_files(self):
        source, target = self.payload()
        publication.restore(source, target)
        for name in publication.PUBLICATION_FILES:
            self.assertEqual((source / name).read_bytes(), (target / name).read_bytes())

    def test_private_notebook_in_payload_is_rejected_before_copy(self):
        source, target = self.payload()
        (source / "notebooks/bitcoin_supply_dynamics.ipynb").write_text("private")
        with self.assertRaisesRegex(ValueError, "allowlist"):
            publication.restore(source, target)
        self.assertFalse((target / "notebooks").exists())

    def test_corrupt_payload_is_rejected_before_copy(self):
        source, target = self.payload()
        (source / "data/processed/bitcoin_daily.csv").write_text("bad data")
        with self.assertRaisesRegex(ValueError, "checksum"):
            publication.restore(source, target)
        self.assertFalse((target / "notebooks").exists())

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
