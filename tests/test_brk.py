from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import pandas as pd

from bitcoin_investment_strategy.fetchers import brk


class BrkDateAlignmentTests(unittest.TestCase):
    def fetch(self, payload, as_of="2009-01-04"):
        response = Mock(url="https://example.invalid/series/price_close/day")
        response.json.return_value = payload
        with patch.object(brk, "BRK_SERIES", {"price_close": "price"}), patch.object(
            brk, "request", return_value=response
        ):
            return brk.fetch_brk_daily(pd.Timestamp(as_of))

    def test_valid_daily_range_preserves_dates_values_and_missing_values(self):
        frame, provenance = self.fetch(
            {"index": "day1", "start": 2, "end": 4, "data": [11, None]}
        )
        self.assertEqual(list(frame.index.strftime("%Y-%m-%d")), ["2009-01-03", "2009-01-04"])
        self.assertEqual(frame.iloc[0, 0], 11)
        self.assertTrue(pd.isna(frame.iloc[1, 0]))
        self.assertEqual(provenance["price_close"]["response_end"], 4)

    def test_equal_length_wrong_or_missing_metadata_is_rejected(self):
        valid = {"index": "day1", "start": 2, "end": 4, "data": [11, 22]}
        for change in (
            {"index": "hour"}, {"start": 100, "end": 102},
            {"end": 3}, {"start": "2"}, {"end": 4.0}, {"start": True},
            {"index": None}, {"start": None}, {"end": None},
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "day1 range"):
                self.fetch({**valid, **change})

    def test_wrong_length_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "expected 2 daily observations"):
            self.fetch({"index": "day1", "start": 2, "end": 4, "data": [11]})

    def test_calendar_alignment_includes_leap_day(self):
        with patch.object(brk, "START_DATE", "2024-02-28"):
            frame, _ = self.fetch(
                {"index": "day1", "start": 5536, "end": 5539, "data": [1, 2, 3]},
                "2024-03-01",
            )
        self.assertEqual(list(frame.index.strftime("%Y-%m-%d")),
                         ["2024-02-28", "2024-02-29", "2024-03-01"])
