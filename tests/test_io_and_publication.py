"""HTTP retry policy, atomic writes, and notebook stripping / release verification."""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
import requests

from bitcoin_investment_strategy import io
from bitcoin_investment_strategy.notebook_html import is_notebook_stripped
from bitcoin_investment_strategy.release_files import NOTEBOOKS

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publication", ROOT / "scripts/publication.py")
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


def response(status, headers=None):
    result = requests.Response()
    result.status_code = status
    result.headers.update(headers or {})
    result.url = "https://example.invalid/data"
    return result


class RequestRetryTests(unittest.TestCase):
    def test_retry_after_is_honored_for_rate_limits_up_to_65s(self):
        ok = response(200)
        with patch.object(io.requests, "get", side_effect=[response(429, {"Retry-After": "60"}), ok]), \
                patch.object(io.time, "sleep") as sleep:
            self.assertIs(io.request("https://example.invalid/data"), ok)
        sleep.assert_called_once_with(60.0)

        with patch.object(io.requests, "get", side_effect=[response(429, {"Retry-After": "120"}), ok]), \
                patch.object(io.time, "sleep") as sleep:
            self.assertIs(io.request("https://example.invalid/data"), ok)
        sleep.assert_called_once_with(65)

    def test_client_errors_fail_without_retrying(self):
        with patch.object(io.requests, "get", return_value=response(404)) as get, \
                patch.object(io.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
                io.request("https://example.invalid/data")
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()

    def test_server_errors_are_retried_and_raise_transient_error(self):
        with patch.object(io.requests, "get", return_value=response(503)) as get, \
                patch.object(io.time, "sleep"):
            with self.assertRaisesRegex(io.TransientRequestError, "after 3 attempts"):
                io.request("https://example.invalid/data", attempts=3)
        self.assertEqual(get.call_count, 3)

    def test_atomic_write_bytes_leaves_no_temp_files(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "sample.txt"
            io.atomic_write_text(target, "hello")
            self.assertEqual(target.read_text(), "hello")
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["sample.txt"])


class ReleaseMetadataTests(unittest.TestCase):
    def test_verify_artifacts_and_release_id(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "data.csv"
            path.write_text("date,price\n2026-01-01,1\n")
            artifacts = {"data.csv": io.artifact_metadata(path)}
            self.assertEqual(artifacts["data.csv"]["data_end"], "2026-01-01")
            io.verify_artifacts({"artifacts": artifacts}, root, [path])
            release = io.release_id(pd.Timestamp("2026-01-01"), artifacts)
            self.assertTrue(release.startswith("2026-01-01-"))
            path.write_text("date,price\n2026-01-01,2\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                io.verify_artifacts({"artifacts": artifacts}, root, [path])
            self.assertNotEqual(release, io.release_id(
                pd.Timestamp("2026-01-01"), {"data.csv": io.artifact_metadata(path)}))


class NotebookReleaseTests(unittest.TestCase):
    def write_notebook(self, path: Path, output_text: str | None = None) -> Path:
        outputs = [{"output_type": "stream", "text": [output_text]}] if output_text else []
        exec_count = 1 if output_text else None
        path.write_text(json.dumps({"cells": [
            {"cell_type": "code", "execution_count": exec_count, "outputs": outputs, "source": []},
        ]}))
        return path

    def test_notebook_data_end_reads_all_three_notebook_formats(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            cases = [
                ("savings.ipynb", "Data release: 2026-09-20-abc123\n", "2026-09-20"),
                ("supply.ipynb", "Release 2026-09-21-def456\n", "2026-09-21"),
                ("demand.ipynb", "release         2026-09-22-ghi789\nData cutoff: 2026-09-22\n", "2026-09-22"),
            ]
            for name, text, expected in cases:
                with self.subTest(name=name):
                    nb = self.write_notebook(base / name, text)
                    self.assertEqual(publication.notebook_data_end(nb), expected)
                    self.assertFalse(publication.is_notebook_stripped(nb))

    def test_committed_notebooks_remain_output_stripped(self):
        for rel in sorted(NOTEBOOKS):
            nb_path = ROOT / rel
            with self.subTest(notebook=rel):
                self.assertTrue(nb_path.is_file(), f"Missing notebook {rel}")
                self.assertTrue(is_notebook_stripped(nb_path), f"{rel} still contains outputs or execution counts")
                self.assertTrue(publication.is_notebook_stripped(nb_path))


if __name__ == "__main__":
    unittest.main()
