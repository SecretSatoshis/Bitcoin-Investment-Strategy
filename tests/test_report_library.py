"""The Report Library price fetch: publication timing, checksums and schema."""
from __future__ import annotations

import gzip
import hashlib
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from bitcoin_investment_strategy.fetchers import report_library
from bitcoin_investment_strategy.fetchers.report_library import ReleaseNotReady
from bitcoin_investment_strategy.io import SourceSchemaError

MASTER = "date,price_close,supply\n2010-08-15,,1\n2010-08-16,0.06,2\n2010-08-17,0.07,3\n"


class ReportLibraryTests(unittest.TestCase):
    def fetch(self, as_of="2010-08-17", report_date="2010-08-17", master=MASTER, sha=None):
        content = gzip.compress(master.encode())
        manifest = {"report_date": report_date, "release_id": report_date,
                    "files": {"master_metrics_data.csv.gz": {"sha256": sha or hashlib.sha256(content).hexdigest()}}}
        responses = [Mock(**{"json.return_value": manifest}), Mock(content=content, url="https://example.invalid/master")]
        with patch.object(report_library, "request", side_effect=responses):
            return report_library.fetch_bitcoin_price(pd.Timestamp(as_of))

    def test_price_starts_on_the_first_traded_day(self):
        frame, provenance = self.fetch()
        self.assertEqual(list(frame.columns), ["price"])
        self.assertEqual(list(frame.index.strftime("%Y-%m-%d")), ["2010-08-16", "2010-08-17"])
        self.assertEqual(provenance["release_id"], "2010-08-17")

    def test_waits_for_a_release_that_has_not_reached_the_cutoff(self):
        with self.assertRaises(ReleaseNotReady):
            self.fetch(report_date="2010-08-16")

    def test_a_data_file_that_disagrees_with_the_manifest_is_not_ready(self):
        with self.assertRaises(ReleaseNotReady):
            self.fetch(sha="0" * 64)

    def test_a_newer_release_cannot_supply_an_earlier_cutoff(self):
        with self.assertRaisesRegex(ValueError, "earlier cutoff"):
            self.fetch(as_of="2010-08-16")

    def test_a_short_data_file_is_refused(self):
        with self.assertRaisesRegex(ValueError, "does not run through"):
            self.fetch(master=MASTER.rsplit("2010-08-17", 1)[0])

    def test_schema_changes_are_schema_errors(self):
        with self.assertRaises(SourceSchemaError):
            self.fetch(master=MASTER.replace("price_close", "close"))
        responses = [Mock(**{"json.return_value": {"report_date": "2010-08-17"}})]
        with patch.object(report_library, "request", side_effect=responses), self.assertRaises(SourceSchemaError):
            report_library.fetch_bitcoin_price(pd.Timestamp("2010-08-17"))


if __name__ == "__main__":
    unittest.main()
