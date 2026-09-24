import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from bitcoin_investment_strategy.savings_report import build_report


class Section3Tests(unittest.TestCase):
    def setUp(self):
        self.prices = pd.Series(100., index=pd.date_range("2022-01-01", "2026-09-21"))
        self.settings = dict(as_of="2026-06-30", annual_income=12000,
                             bitcoin_fraction=.1, cash_fraction=.1, cash_apy=0.)

    def test_flat_price_zero_interest_has_no_investment_gain(self):
        assumptions, tables = build_report(self.prices, **self.settings)
        self.assertTrue(assumptions["is_quarter_end"])
        s = tables["cohort_summary"].set_index("cohort_year")
        self.assertEqual(list(s.index), [2026, 2025, 2024, 2023, 2022])
        self.assertAlmostEqual(s.loc[2026, "btc_held"], 6.)
        self.assertAlmostEqual(s.loc[2026, "total_contributed_usd"], 1200.)
        self.assertAlmostEqual(s.loc[2022, "total_contributed_usd"], 10800.)
        np.testing.assert_allclose(s.total_gain_usd, 0., atol=1e-8)
        np.testing.assert_allclose(s.advantage_vs_cash_usd, 0., atol=1e-8)
        np.testing.assert_allclose(tables["ytd_summary"].total_gain_ytd_usd, 0., atol=1e-8)

    def test_ytd_counts_january_price_change_and_january_deposit_once(self):
        prices = self.prices.copy()
        prices.loc["2026-01-01":] = 200.
        _, t = build_report(prices, **{**self.settings, "as_of": "2026-01-01"})
        y = t["ytd_summary"].set_index("cohort_year")
        # 2025 saver holds 12 BTC + $1,200 cash at Dec 31. Jan 1 doubles those BTC.
        self.assertAlmostEqual(y.loc[2025, "opening_total_value_usd"], 2400.)
        self.assertAlmostEqual(y.loc[2025, "total_contributed_ytd_usd"], 200.)
        self.assertAlmostEqual(y.loc[2025, "total_gain_ytd_usd"], 1200.)
        self.assertAlmostEqual(y.loc[2025, "closing_total_value_usd"], 3800.)
        self.assertAlmostEqual(y.loc[2026, "opening_total_value_usd"], 0.)
        self.assertAlmostEqual(y.loc[2026, "total_gain_ytd_usd"], 0.)
        self.assertAlmostEqual(y.loc[2026, "btc_accumulated_ytd"], .5)

    def test_ytd_reconciliation_with_interest_and_different_opening_balances(self):
        prices = self.prices.copy()
        prices.loc["2024-06-01":] = 150.
        _, t = build_report(prices, **{**self.settings, "cash_apy": .03})
        y = t["ytd_summary"]
        np.testing.assert_allclose(y.opening_total_value_usd + y.total_contributed_ytd_usd + y.total_gain_ytd_usd,
                                   y.closing_total_value_usd, atol=1e-8)
        np.testing.assert_allclose(y.btc_gain_ytd_usd + y.cash_interest_ytd_usd, y.total_gain_ytd_usd)
        opening_advantage = y.opening_total_value_usd - y.cash_only_opening_value_usd
        closing_advantage = y.closing_total_value_usd - y.cash_only_closing_value_usd
        np.testing.assert_allclose(closing_advantage - opening_advantage, y.incremental_advantage_ytd_usd, atol=1e-8)
        s = t["contribution_schedule"]
        np.testing.assert_allclose(s.total_contribution_usd, s.cash_only_contribution_usd)

    def test_cutoff_excludes_future_prices_and_purchases(self):
        _, expected = build_report(self.prices, **self.settings)
        later_changed = self.prices.copy()
        later_changed.loc["2026-07-01":] = 1000000.
        _, actual = build_report(later_changed, **self.settings)
        for name in expected:
            pd.testing.assert_frame_equal(expected[name], actual[name])
        self.assertEqual(actual["cohort_paths"].date.max(), pd.Timestamp("2026-06-30"))
        self.assertEqual(actual["contribution_schedule"].date.max(), pd.Timestamp("2026-06-01"))

    def test_completed_horizons_can_have_ytd_gains_without_contributions(self):
        _, t = build_report(self.prices, **{**self.settings, "cash_apy": .03,
                                          "still_buying": False, "stop_after_yrs": 1})
        y = t["ytd_summary"].set_index("cohort_year")
        self.assertEqual(y.loc[2022, "total_contributed_ytd_usd"], 0.)
        self.assertGreater(y.loc[2022, "cash_interest_ytd_usd"], 0.)

    def test_invalid_cutoffs_and_incomplete_cohorts_fail(self):
        for change in [dict(as_of="2026-09-30"), dict(as_of="2026-06-30T12:00:00"),
                       dict(as_of="2026-06-30T00:00:00Z"), dict(cohort_years=[2026, 2021]),
                       dict(cohort_years=[2026, 2026]), dict(cohort_years=[2025]),
                       dict(cohort_years=[2026, 2027])]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_report(self.prices, **{**self.settings, **change})

    def test_all_supported_cadences_keep_benchmark_contributions_equal(self):
        for cadence in ["monthly", "weekly", "biweekly"]:
            _, t = build_report(self.prices, **{**self.settings, "cadence": cadence})
            y = t["ytd_summary"]
            np.testing.assert_allclose(y.total_gain_ytd_usd, 0., atol=1e-8)
            s = t["contribution_schedule"]
            np.testing.assert_allclose(s.total_contribution_usd, s.cash_only_contribution_usd)


if __name__ == "__main__":
    unittest.main()
