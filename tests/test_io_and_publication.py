"""HTTP retry policy and the weekly notebook publication rule."""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import requests

from bitcoin_investment_strategy import io

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
    def test_retry_after_is_honored_for_rate_limits(self):
        ok = response(200)
        with patch.object(io.requests, "get", side_effect=[response(429, {"Retry-After": "7"}), ok]), \
                patch.object(io.time, "sleep") as sleep:
            self.assertIs(io.request("https://example.invalid/data"), ok)
        sleep.assert_called_once_with(7.0)

    def test_client_errors_fail_without_retrying(self):
        with patch.object(io.requests, "get", return_value=response(404)) as get, \
                patch.object(io.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
                io.request("https://example.invalid/data")
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()

    def test_server_errors_are_retried(self):
        with patch.object(io.requests, "get", return_value=response(503)) as get, \
                patch.object(io.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "after 3 attempts"):
                io.request("https://example.invalid/data", attempts=3)
        self.assertEqual(get.call_count, 3)


class WeeklyNotebookTests(unittest.TestCase):
    def notebook(self, directory, release_date):
        path = Path(directory) / "notebook.ipynb"
        path.write_text(json.dumps({"cells": [{"cell_type": "code", "outputs": [
            {"output_type": "stream", "text": [f"Shared data release: {release_date}-abc123\n"]}]}]}))
        return path

    def test_notebook_is_committed_for_sunday_data_or_after_a_week(self):
        with TemporaryDirectory() as directory:
            committed = self.notebook(directory, "2026-09-20")
            self.assertEqual(publication.notebook_data_end(committed), "2026-09-20")
            self.assertTrue(publication.notebook_due("2026-09-27", committed))   # Sunday
            self.assertFalse(publication.notebook_due("2026-09-23", committed))  # midweek
            self.assertTrue(publication.notebook_due("2026-09-26", self.notebook(directory, "2026-09-19")))
            self.assertTrue(publication.notebook_due("2026-09-23", Path(directory) / "missing.ipynb"))


if __name__ == "__main__":
    unittest.main()
