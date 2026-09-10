import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
import numpy as np
import pandas as pd
from bitcoin_investment_strategy import pipeline,validation
from bitcoin_investment_strategy.config import ROOT
from bitcoin_investment_strategy.fetchers import fred


class ReviewValidationTests(unittest.TestCase):
    def test_income_rejects_empty_null_infinite_duplicate_fractional_and_future_years(self):
        for years,values in [([],[]),([2025],[np.nan]),([2025],[np.inf]),([2025],[-1]),
                             ([2025,2025],[1,2]),([2025.5],[1]),([2027],[1]),([2010],[1])]:
            frame=pd.DataFrame({'Year':years,'median_household_income_usd':values})
            with self.subTest(years=years,values=values),self.assertRaises(ValueError):
                validation.validate_income(frame,pd.Timestamp('2026-09-09'))
        validation.validate_income(pd.DataFrame({'Year':[2024],'median_household_income_usd':[80000]}),pd.Timestamp('2026-09-09'))

    def test_fred_missing_values_are_fatal(self):
        response=Mock(text='observation_date,MEHOINUSA646N\n2025-01-01,.\n')
        with patch.object(fred,'request',return_value=response),self.assertRaises(ValueError):fred.fetch_fred_median_income()

    def test_cache_requires_previous_membership_and_unchanged_bytes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            cache=Path(tmp)/'income.csv';cache.write_text('Year,median_household_income_usd\n2025,80000\n')
            manifest=Path(tmp)/'manifest.json'
            def offline():raise TimeoutError('offline')
            with self.assertRaisesRegex(RuntimeError,'not verified'):
                pipeline._cached_fetch('income',offline,cache,cache_manifest_path=manifest)
            manifest.write_text(json.dumps({'artifacts':{str(cache.relative_to(ROOT)):{'sha256':hashlib.sha256(cache.read_bytes()).hexdigest()}}}))
            cache.write_text('Year,median_household_income_usd\n2025,999999999\n')
            with self.assertRaisesRegex(RuntimeError,'not verified'):
                pipeline._cached_fetch('income',offline,cache,cache_manifest_path=manifest)

    def test_manifest_cannot_omit_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'manifest.json';path.write_text(json.dumps({'schema_version':1,'artifacts':{}}))
            with self.assertRaisesRegex(ValueError,'complete expected'):validation.validate_release_manifest(path)

    def test_processed_price_and_market_cap_are_checked(self):
        daily=pd.read_csv(ROOT/'data/processed/bitcoin_daily.csv',parse_dates=['date']).set_index('date')
        for column,value in [('price',-100),('market_cap_usd',999)]:
            broken=daily.copy();broken.loc[broken.index[-1],column]=value
            with self.subTest(column=column),self.assertRaises(ValueError):validation.validate_bitcoin_daily(broken)

    def test_unused_stale_metric_cannot_publish_truncated_release(self):
        raw=pd.read_csv(ROOT/'data/raw/brk/brk_daily.csv',parse_dates=['date']).set_index('date')
        cutoff=raw.index[-1];raw.loc[raw.index>pd.Timestamp('2022-12-31'),'hash_rate']=np.nan
        with patch.object(pipeline,'ensure_directories'),patch.object(pipeline,'fetch_brk_daily',return_value=(raw,{})),patch.object(pipeline,'atomic_write_csv') as write:
            with self.assertRaisesRegex(ValueError,'refusing truncated release'):pipeline.update_data(cutoff)
            write.assert_not_called()

    def test_artifact_bundle_includes_every_manifest_member(self):
        workflow=(ROOT/'.github/workflows/pipeline-health.yml').read_text()
        upload=workflow.split('path: |')[1].split('if-no-files-found')[0]
        prefixes=[line.strip() for line in upload.splitlines() if line.strip()]
        manifest=json.loads((ROOT/'data/manifests/data_manifest.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            target=Path(tmp)
            for prefix in prefixes:
                shutil.copytree(ROOT/prefix,target/prefix,dirs_exist_ok=True)
            validation.validate_release_manifest(target/'data/manifests/data_manifest.json',root=target)
            self.assertTrue(all(any(name.startswith(prefix) for prefix in prefixes) for name in manifest['artifacts']))
