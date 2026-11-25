"""The Report Library fetch: publication timing, checksums and schema."""
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
ANNUAL = ("series,year,value,unit,source,source_url,note,retrieved_date\n"
          "us_median_household_income_usd,2008,50303,current USD,FRED,,,2010-08-17\n"
          "us_median_household_income_usd,2009,49777,current USD,FRED,,,2010-08-17\n"
          "world_population,2009,6.8e9,people,World Bank,,,2010-08-17\n")


class ReportLibraryTests(unittest.TestCase):
    def fetch(self, as_of="2010-08-17", report_date="2010-08-17", master=MASTER, annual=ANNUAL, sha=None):
        master_bytes, annual_bytes = gzip.compress(master.encode()), annual.encode()
        manifest = {"report_date": report_date, "release_id": report_date, "files": {
            "master_metrics_data.csv.gz": {"sha256": sha or hashlib.sha256(master_bytes).hexdigest()},
            "annual_reference_data.csv": {"sha256": hashlib.sha256(annual_bytes).hexdigest()},
        }}
        responses = [Mock(**{"json.return_value": manifest}), Mock(content=master_bytes), Mock(content=annual_bytes)]
        with patch.object(report_library, "request", side_effect=responses):
            return report_library.fetch_savings_inputs(pd.Timestamp(as_of))

    def test_price_starts_on_the_first_traded_day_and_income_comes_from_the_same_release(self):
        price, income, provenance = self.fetch()
        self.assertEqual(list(price.columns), ["price"])
        self.assertEqual(list(price.index.strftime("%Y-%m-%d")), ["2010-08-16", "2010-08-17"])
        self.assertEqual(income.to_dict("list"), {"Year": [2008, 2009], "median_household_income_usd": [50303, 49777]})
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
        with self.assertRaises(SourceSchemaError):
            self.fetch(annual=ANNUAL.replace("us_median_household_income_usd", "income"))
        responses = [Mock(**{"json.return_value": {"report_date": "2010-08-17"}})]
        with patch.object(report_library, "request", side_effect=responses), self.assertRaises(SourceSchemaError):
            report_library.fetch_savings_inputs(pd.Timestamp("2010-08-17"))

    def test_allow_slice_backfills_earlier_cutoff_and_records_provenance(self):
        master_bytes = gzip.compress(MASTER.encode())
        annual_with_2010 = (
            ANNUAL + "us_median_household_income_usd,2010,49276,current USD,FRED,,,2011-01-01\n"
        ).encode()
        etf_daily = (
            "date,fund,btc_held\n2010-08-15,IBIT,10\n2010-08-16,IBIT,12\n2010-08-17,IBIT,15\n"
        ).encode()
        etf_quarterly = (
            "fund,quarter_end,btc\nALL,2010-06-30,10\nALL,2010-09-30,15\n"
        ).encode()
        manifest = {
            "report_date": "2010-08-17",
            "release_id": "2010-08-17",
            "files": {
                "master_metrics_data.csv.gz": {"sha256": hashlib.sha256(master_bytes).hexdigest()},
                "annual_reference_data.csv": {"sha256": hashlib.sha256(annual_with_2010).hexdigest()},
                "etf_daily.csv": {"sha256": hashlib.sha256(etf_daily).hexdigest()},
                "etf_quarterly.csv": {"sha256": hashlib.sha256(etf_quarterly).hexdigest()},
            },
        }
        responses = [
            Mock(**{"json.return_value": manifest}),
            Mock(content=master_bytes),
            Mock(content=annual_with_2010),
            Mock(content=etf_daily),
            Mock(content=etf_quarterly),
        ]
        with patch.object(report_library, "request", side_effect=responses) as req:
            raw = report_library.fetch_raw_release(
                pd.Timestamp("2010-08-16"),
                ("etf_daily.csv", "etf_quarterly.csv"),
                allow_slice=True,
            )
            # Reusing the raw release triggers zero extra HTTP calls.
            price, income, sav_prov = report_library.fetch_savings_inputs(
                pd.Timestamp("2010-08-16"), allow_slice=True, release=raw,
            )
            daily, annual, extra, res_prov = report_library.fetch_release_files(
                pd.Timestamp("2010-08-16"),
                ["price_close", "supply"],
                ("etf_daily.csv", "etf_quarterly.csv"),
                allow_slice=True,
                release=raw,
            )
        self.assertEqual(req.call_count, 5)
        self.assertEqual(list(price.index.strftime("%Y-%m-%d")), ["2010-08-16"])
        self.assertEqual(list(daily.index.strftime("%Y-%m-%d")), ["2010-08-15", "2010-08-16"])
        self.assertEqual(income["Year"].tolist(), [2008, 2009])
        self.assertEqual(annual["year"].max(), 2009)
        self.assertEqual(extra["etf_daily.csv"]["date"].tolist(), ["2010-08-15", "2010-08-16"])
        self.assertEqual(extra["etf_quarterly.csv"]["quarter_end"].tolist(), ["2010-06-30"])
        self.assertEqual(sav_prov["sliced_from_report_date"], "2010-08-17")
        self.assertEqual(res_prov["sliced_from_report_date"], "2010-08-17")


if __name__ == "__main__":
    unittest.main()
