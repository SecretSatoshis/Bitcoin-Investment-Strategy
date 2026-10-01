"""The committed data release and the notebook that reads it."""
from __future__ import annotations

import unittest

import nbformat
import pandas as pd

from bitcoin_investment_strategy.config import ROOT
from bitcoin_investment_strategy.validation import validate_bitcoin_daily, validate_release_manifest


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

    def test_release_publishes_only_what_the_notebook_reads(self) -> None:
        self.assertEqual(list(self.daily.columns), ["price"])

    def test_notebook_is_an_offline_consumer(self) -> None:
        forbidden = ("requests.get", "subprocess.run", "nbconvert", "secretsatoshis.github.io")
        notebook = nbformat.read(ROOT / "notebooks" / "bitcoin_savings_plan.ipynb", as_version=4)
        code = "\n".join(cell.source for cell in notebook.cells if cell.cell_type == "code")
        self.assertIn("data/processed/bitcoin_daily.csv", code)
        self.assertIn("data/processed/median_household_income_annual.csv", code)
        for pattern in forbidden:
            self.assertNotIn(pattern, code, f"the notebook contains {pattern}")


if __name__ == "__main__":
    unittest.main()
