from __future__ import annotations

import sys
import unittest
from pathlib import Path

import nbformat
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bitcoin_investment_strategy.validation import (  # noqa: E402
    validate_bitcoin_daily,
    validate_release_manifest,
)


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.daily = pd.read_csv(ROOT / "data/processed/bitcoin_daily.csv", parse_dates=["date"]).set_index("date")

    def test_manifest_and_data_contracts(self) -> None:
        validate_release_manifest(ROOT / "data/manifests/data_manifest.json")
        validate_bitcoin_daily(self.daily)
        income = pd.read_csv(ROOT / "data/processed/median_household_income_annual.csv")
        self.assertFalse(income["Year"].duplicated().any())
        self.assertTrue(income["median_household_income_usd"].gt(0).all())

    def test_known_supply_regressions(self) -> None:
        self.assertTrue(np.isclose(self.daily.loc["2009-01-09", "subsidy_daily"], 700.0))
        first = self.daily.index[self.daily["utxos_over_1y_old_supply"].gt(0)][0]
        self.assertEqual(first, pd.Timestamp("2010-01-09"))

    def test_price_is_not_duplicated(self) -> None:
        self.assertIn("price", self.daily.columns)
        self.assertNotIn("price_close", self.daily.columns)

    def test_notebook_is_an_offline_consumer(self) -> None:
        forbidden = ("requests.get", "subprocess.run", "nbconvert", "bitview.space/api")
        notebook = nbformat.read(ROOT / "notebooks" / "bitcoin_savings_plan.ipynb", as_version=4)
        code = "\n".join(cell.source for cell in notebook.cells if cell.cell_type == "code")
        self.assertIn("data/processed/bitcoin_daily.csv", code)
        self.assertIn("data/processed/median_household_income_annual.csv", code)
        for pattern in forbidden:
            self.assertNotIn(pattern, code, f"savings plan still contains {pattern}")


if __name__ == "__main__":
    unittest.main()
