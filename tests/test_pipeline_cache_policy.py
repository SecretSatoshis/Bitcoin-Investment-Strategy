"""L6 — the committed cache substitutes for a slow source, never for a dead one."""

from __future__ import annotations

import unittest
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from bitcoin_investment_strategy import pipeline
from bitcoin_investment_strategy.config import FRED_CACHE_MAX_AGE_YEARS, ROOT


class CachedFetchPolicyTests(unittest.TestCase):
    def _cache(self, tmp: Path, years: list[int]) -> Path:
        path = tmp / "cache.csv"
        pd.DataFrame(
            {"Year": years, "median_household_income_usd": [1.0] * len(years)}
        ).to_csv(path, index=False)
        (tmp / "manifest.json").write_text(json.dumps({"artifacts": {
            str(path.relative_to(ROOT)): {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        }}))
        return path

    def test_transient_failure_falls_back_to_cache(self):
        with TemporaryDirectory(dir=ROOT) as tmpdir:
            path = self._cache(Path(tmpdir), [2023, 2024])

            def fetcher():
                raise TimeoutError("connection stalled")

            frame, provenance = pipeline._cached_fetch("t", fetcher, path, cache_manifest_path=path.parent / "manifest.json")
            self.assertEqual(provenance["status"], "cached")
            self.assertEqual(len(frame), 2)

    def test_schema_change_is_fatal_rather_than_silently_cached(self):
        with TemporaryDirectory(dir=ROOT) as tmpdir:
            path = self._cache(Path(tmpdir), [2023, 2024])

            def fetcher():
                raise ValueError("FRED median-income response has an unexpected schema")

            with self.assertRaises(RuntimeError) as ctx:
                pipeline._cached_fetch("t", fetcher, path, cache_manifest_path=path.parent / "manifest.json")
            self.assertIn("unexpected schema", str(ctx.exception))

    def test_stale_cache_is_refused(self):
        with TemporaryDirectory(dir=ROOT) as tmpdir:
            path = self._cache(Path(tmpdir), [2015])

            def fetcher():
                raise TimeoutError("connection stalled")

            def stale(frame):
                return "it is far too old"

            with self.assertRaises(RuntimeError) as ctx:
                pipeline._cached_fetch("t", fetcher, path, cache_manifest_path=path.parent / "manifest.json", stale_cache_check=stale)
            self.assertIn("no longer usable", str(ctx.exception))

    def test_missing_year_column_has_a_clear_stale_cache_error(self):
        reason = pipeline._fred_cache_staleness(
            pd.DataFrame({"unexpected": [2025]}), pd.Timestamp("2026-08-29")
        )
        self.assertEqual(reason, "it contains no usable Year column")

    def test_fresh_cache_passes_the_age_check(self):
        with TemporaryDirectory(dir=ROOT) as tmpdir:
            path = self._cache(Path(tmpdir), [2025])

            def fetcher():
                raise TimeoutError("connection stalled")

            def stale(frame):
                age = 2026 - int(pd.to_numeric(frame["Year"]).max())
                return None if age <= FRED_CACHE_MAX_AGE_YEARS else "too old"

            frame, provenance = pipeline._cached_fetch(
                "t", fetcher, path, cache_manifest_path=path.parent / "manifest.json", stale_cache_check=stale
            )
            self.assertEqual(provenance["status"], "cached")

    def test_budget_tolerates_the_sources_publication_lag(self):
        # MEHOINUSA646N lands roughly a year late; the budget must not trip on that.
        self.assertGreaterEqual(FRED_CACHE_MAX_AGE_YEARS, 2)


if __name__ == "__main__":
    unittest.main()
