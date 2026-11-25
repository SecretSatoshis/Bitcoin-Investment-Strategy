"""Supply and demand release: analysis helpers, the daily table, treasuries, the ETF checks,
the CoinGecko 24-hour rule and the notebooks' setup cells."""
import ast
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from nbclient.exceptions import CellExecutionError
import nbformat
import numpy as np
import pandas as pd

from bitcoin_investment_strategy.config import ROOT
from bitcoin_investment_strategy.io import TransientRequestError
from bitcoin_investment_strategy.notebook_html import export_notebooks_html
from bitcoin_investment_strategy.research import treasuries
from bitcoin_investment_strategy.research.analysis import (
    covered_periods, forward_change, halving_dates, validate_cohorts,
)
from bitcoin_investment_strategy.research.config import REPORT_LIBRARY_COLUMNS
from bitcoin_investment_strategy.research.transforms import build_bitcoin_daily, build_company_treasuries
from bitcoin_investment_strategy.research.validation import (
    find_etf_cosponsors, find_fund_issuer_overlap, validate_etf, validate_etf_quarterly,
)

_exec_spec = importlib.util.spec_from_file_location("execute_notebooks", ROOT / "scripts/execute_notebooks.py")
execute_notebooks = importlib.util.module_from_spec(_exec_spec)
_exec_spec.loader.exec_module(execute_notebooks)


class AnalysisTests(unittest.TestCase):
    def test_final_calendar_day_counts_for_each_period(self):
        for code, start, end in [("W", "2026-01-05", "2026-01-11"), ("M", "2026-01-01", "2026-01-31"),
                                 ("Q", "2026-01-01", "2026-03-31"), ("Y", "2026-01-01", "2026-12-31")]:
            with self.subTest(code=code):
                index = pd.DatetimeIndex([end])
                self.assertTrue(covered_periods(index, code, start, end)[0])
                self.assertFalse(covered_periods(index, code, start, pd.Timestamp(end) - pd.Timedelta(days=1))[0])
                self.assertFalse(covered_periods(index, code, pd.Timestamp(start) + pd.Timedelta(days=1), end)[0])

    def test_cohorts_accept_rounding_and_reject_wrong_stocks(self):
        frame = pd.DataFrame({"supply": [100.], "lth_supply": [60.], "sth_supply": [40. + 0.004],
                              "utxos_over_1y_old_supply": [50.]})
        validate_cohorts(frame)
        for field, value in [("sth_supply", 1_000_000), ("lth_supply", -1),
                             ("utxos_over_1y_old_supply", 101), ("lth_supply", np.nan)]:
            with self.subTest(field=field, value=value):
                changed = frame.copy()
                changed[field] = value
                with self.assertRaises(ValueError):
                    validate_cohorts(changed)

    def test_forward_window_requires_all_90_days(self):
        index = pd.date_range("2026-01-01", periods=91)
        series = pd.Series(np.linspace(100, 120, 91), index=index)
        self.assertEqual(forward_change(series, index[0], index[-1]), "+20%")
        self.assertEqual(forward_change(series, index[0], index[2]), "pending (2/90d)")
        self.assertEqual(forward_change(series, index[0], index[0]), "still open")
        self.assertEqual(forward_change(series.drop(index[50]), index[0], index[-1]), "incomplete data")

    def test_halvings_follow_the_protocol_reward_schedule(self):
        halvings = halving_dates()
        self.assertEqual([n for n, _, _ in halvings], [1, 2, 3, 4])
        self.assertEqual(halvings[0], (1, pd.Timestamp("2012-11-28"), 25.0))
        self.assertEqual(halvings[-1], (4, pd.Timestamp("2024-04-20"), 3.125))



class ReleaseTests(unittest.TestCase):
    def test_daily_table_from_the_release(self):
        dates = pd.date_range("2026-01-01", periods=3, name="date")
        release = pd.DataFrame({column: 1.0 for column in REPORT_LIBRARY_COLUMNS}, index=dates)
        release["supply"] = 100.0
        release["price_close"] = [None, 10.0, 11.0]
        release["utxos_under_2y_old_supply"] = 100.004  # rounding: older supply is clipped at zero
        release["subsidy_cumulative"] = [10.0, 13.125, 16.25]
        release["cm_efficiency_source_date"] = "2025-12-01"
        daily = build_bitcoin_daily(release, dates[-1])
        self.assertEqual(daily["utxos_over_2y_old_supply"].tolist(), [0.0, 0.0, 0.0])
        self.assertEqual(daily["subsidy_daily"].iloc[1:].tolist(), [3.125, 3.125])
        self.assertTrue(pd.isna(daily["market_cap_usd"].iloc[0]))
        release["cm_efficiency_source_date"] = "2024-12-01"
        with self.assertRaisesRegex(ValueError, "one year"):
            build_bitcoin_daily(release, dates[-1])

    def test_treasury_pages_are_read_until_the_reported_total_is_reached(self):
        def page(records, total):
            return Mock(url="https://example.invalid", **{"json.return_value": {"companies": records, "total_holdings": total}})

        full = [{"name": f"c{i}", "total_holdings": 1.0} for i in range(treasuries.PAGE_SIZE)]
        with patch.object(treasuries, "request", side_effect=[page(full, 251.0), page([{"name": "last", "total_holdings": 1.0}], 251.0)]):
            frame, _ = treasuries.fetch_public_treasuries("companies")
        self.assertEqual(len(frame), 251)
        with patch.object(treasuries, "request", return_value=page([{"name": "a", "total_holdings": 1.0}], 5.0)):
            with self.assertRaisesRegex(ValueError, "reported"):
                treasuries.fetch_public_treasuries("companies")

    def test_etf_tables_must_add_up(self):
        tables = {
            "etf_daily.csv": pd.read_csv(ROOT / "data/research/etf_daily.csv", parse_dates=["date"]),
            "etf_totals_daily.csv": pd.read_csv(ROOT / "data/research/etf_totals_daily.csv", parse_dates=["date"]),
            "etf_quarterly.csv": pd.read_csv(ROOT / "data/research/etf_quarterly.csv", parse_dates=["quarter_end"]),
        }
        validate_etf(tables)
        broken = dict(tables, **{"etf_totals_daily.csv": tables["etf_totals_daily.csv"].assign(
            total_btc=lambda frame: frame.total_btc + 1)})
        with self.assertRaisesRegex(ValueError, "sum of funds"):
            validate_etf(broken)
        no_all = tables["etf_quarterly.csv"][tables["etf_quarterly.csv"]["fund"] != "ALL"]
        with self.assertRaisesRegex(ValueError, "ALL"):
            validate_etf_quarterly(no_all)
        no_cost = tables["etf_quarterly.csv"].assign(cost_per_btc=np.nan)
        with self.assertRaisesRegex(ValueError, "cost_per_btc"):
            validate_etf_quarterly(no_cost)

    def test_coingecko_api_key_header_pre_dedupe_check_and_transient_error(self):
        def page(records, total):
            return Mock(url="https://example.invalid", **{"json.return_value": {"companies": records, "total_holdings": total}})

        # Duplicate entity names sum to total_holdings BEFORE dedupe (2 + 1 = 3).
        duped = [{"name": "DupCorp", "total_holdings": 2.0}, {"name": "DupCorp", "total_holdings": 1.0}]
        with patch.dict(os.environ, {"COINGECKO_API_KEY": "demo-secret-key"}), \
                patch.object(treasuries, "request", return_value=page(duped, 3.0)) as req:
            frame, prov = treasuries.fetch_public_treasuries("companies")
        self.assertEqual(req.call_args.kwargs["headers"], {"x-cg-demo-api-key": "demo-secret-key"})
        self.assertTrue(prov["authenticated"])
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame["btc"].iloc[0], 2.0)

        # Empty/whitespace key falls back cleanly to keyless headers.
        with patch.dict(os.environ, {"COINGECKO_API_KEY": "   "}), \
                patch.object(treasuries, "request", return_value=page([{"name": "A", "total_holdings": 1.0}], 1.0)) as req:
            _, prov = treasuries.fetch_public_treasuries("companies")
        self.assertEqual(req.call_args.kwargs["headers"], {})
        self.assertFalse(prov["authenticated"])

        # Transient network/429 failure raises CoinGeckoTransientError specifically.
        with patch.object(treasuries, "request", side_effect=TransientRequestError("429")):
            with self.assertRaises(treasuries.CoinGeckoTransientError):
                treasuries.fetch_public_treasuries("companies")

    def test_private_spacex_and_fund_name_word_boundaries(self):
        raw = pd.DataFrame({
            "entity": [
                "Strategy",
                "Space Exploration Technologies Corp.",
                "Netflix",
                "Rocketfuel",
                "CleanSpark",
                "DarkHorse Technologies",
                "Galaxy Digital Holdings Ltd",
            ],
            "ticker": ["MSTR.US", "SPCX", "NFLX.US", "RKFL.US", "CLSK.US", "DRK.US", "GLXY.US"],
            "btc": [100.0, 18712.0, 1.0, 1.0, 13470.0, 22.7, 21084.0],
        })
        built = build_company_treasuries(raw, pd.Timestamp("2026-11-23"))
        by_entity = built.set_index("entity")["ownership_type"]
        self.assertEqual(by_entity["Space Exploration Technologies Corp."], "private")
        self.assertEqual(by_entity["Strategy"], "public")
        # None of Netflix, Rocketfuel, CleanSpark, DarkHorse, Galaxy Digital false-match FUND_NAME_PATTERN.
        self.assertFalse(find_fund_issuer_overlap(built["entity"]).any())
        # Galaxy Digital is flagged separately as an ETF co-sponsor.
        self.assertEqual(built.loc[find_etf_cosponsors(built["entity"]), "entity"].tolist(),
                         ["Galaxy Digital Holdings Ltd"])
        # Real ETF issuers and sponsors (including ARK and WisdomTree) ARE matched.
        issuers = pd.Series(["ARK 21Shares Bitcoin ETF", "WisdomTree Bitcoin Fund", "BlackRock", "Grayscale"])
        self.assertTrue(find_fund_issuer_overlap(issuers).all())

    def test_government_classifications_cover_uae_venezuela_without_dead_rows(self):
        ref = pd.read_csv(ROOT / "data/reference/government_acquisition_types.csv").set_index("entity")
        self.assertEqual(ref.loc["United Arab Emirates", "acquisition_type"], "mined")
        self.assertEqual(ref.loc["Venezuela", "acquisition_type"], "seized")
        self.assertFalse((ref["acquisition_type"] == "unclassified").any())
        for removed in ("Ukraine", "Ukraine (holdings of public officials)", "Kazakhstan", "Taiwan"):
            self.assertNotIn(removed, ref.index)

    def test_execute_notebooks_error_classification_and_html_export(self):
        transient = CellExecutionError("tb", "CoinGeckoTransientError", "429 Too Many Requests")
        bug = CellExecutionError("tb", "KeyError", "'missing_col'")
        self.assertTrue(execute_notebooks.is_coingecko_transient_error(transient))
        self.assertFalse(execute_notebooks.is_coingecko_transient_error(bug))
        self.assertIn(ROOT / "notebooks/bitcoin_supply_dynamics.ipynb", execute_notebooks.NOTEBOOKS)
        self.assertEqual(execute_notebooks.OPTIONAL_NOTEBOOKS, [ROOT / "notebooks/bitcoin_demand_dynamics.ipynb"])

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            nb = nbformat.v4.new_notebook(cells=[
                nbformat.v4.new_markdown_cell("# Demo\n\nSummary text."),
                nbformat.v4.new_code_cell("print('ok')", outputs=[
                    nbformat.v4.new_output("stream", name="stdout", text="Data release: 2026-11-23\n")
                ]),
            ])
            nb_path = base / "bitcoin_savings_plan.ipynb"
            nbformat.write(nb, nb_path)
            written = export_notebooks_html([nb_path], base / "pages", data_end="2026-11-23")
            self.assertTrue((base / "pages/index.html").is_file())
            self.assertTrue((base / "pages/.nojekyll").is_file())
            self.assertIn("Data release: 2026-11-23", (base / "pages/bitcoin_savings_plan.html").read_text())
            self.assertGreaterEqual(len(written), 2)

    def test_coingecko_copies_are_used_only_within_24_hours(self):
        frame = pd.DataFrame({"entity": ["a"], "btc": [1.0]})
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            fetch = Mock(return_value=(frame, {}))
            with patch.object(treasuries, "fetch_public_treasuries", fetch):
                treasuries._snapshot("companies", cache)
                treasuries._snapshot("companies", cache)
                self.assertEqual(fetch.call_count, 1)
                stale = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=25)
                (cache / "companies.json").write_text(json.dumps({"retrieved_at_utc": stale.isoformat()}))
                treasuries._snapshot("companies", cache)
                self.assertEqual(fetch.call_count, 2)

    def test_notebook_setup_finds_the_repository_from_both_launch_directories(self):
        original = Path.cwd()
        try:
            for name in ["bitcoin_supply_dynamics", "bitcoin_demand_dynamics"]:
                notebook = json.loads((ROOT / "notebooks" / f"{name}.ipynb").read_text())
                tree = ast.parse("".join(notebook["cells"][2]["source"]))
                nodes = [node for node in tree.body if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "ROOT" for target in node.targets)]
                for directory in [ROOT, ROOT / "notebooks"]:
                    os.chdir(directory)
                    scope = {"Path": Path}
                    exec(compile(ast.Module(nodes, type_ignores=[]), "setup", "exec"), scope)
                    self.assertEqual(scope["ROOT"], ROOT)
        finally:
            os.chdir(original)


if __name__ == "__main__":
    unittest.main()
