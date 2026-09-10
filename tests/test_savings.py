import unittest
import numpy as np
import pandas as pd
from bitcoin_investment_strategy.savings import run_plan, prepare_prices, validate_allocations, milestone_status, money_weighted_return


class SavingsTests(unittest.TestCase):
    def setUp(self):
        self.prices = pd.Series(100., index=pd.date_range('2024-01-01','2024-12-31'))

    def test_each_cadence_preserves_annual_budget_and_cash_equation(self):
        for cadence,count in [('weekly',53),('biweekly',27),('monthly',12)]:
            with self.subTest(cadence=cadence):
                plan = run_plan(self.prices.index[0],10000,10000,cadence,prices=self.prices)
                self.assertEqual(len(plan.attrs['buy_dates']),count)
                self.assertAlmostEqual(plan.btc_contributed.iloc[-1],10000)
                self.assertAlmostEqual(plan.coins.iloc[-1],100)
                days = (plan.index[-1]-pd.DatetimeIndex(plan.attrs['buy_dates'])).days
                expected_cash = np.sum(np.asarray(plan.attrs['cash_contributions'])*1.03**(days/365.25))
                self.assertAlmostEqual(plan.cash_value.iloc[-1],expected_cash,places=7)
                self.assertAlmostEqual(plan.cost_basis.iloc[-1],100)

    def test_missing_buy_day_is_rejected_instead_of_using_previous_price(self):
        prices = self.prices.drop(pd.Timestamp('2024-02-01'))
        with self.assertRaisesRegex(ValueError,'missing calendar'):
            run_plan(prices.index[0],1200,0,prices=prices)

    def test_leading_zero_history_is_trimmed_but_invalid_trading_prices_fail(self):
        prices = self.prices.copy();prices.iloc[:2] = 0
        self.assertEqual(prepare_prices(prices).index[0],pd.Timestamp('2024-01-03'))
        for value in [0,-1,np.nan,np.inf]:
            prices = self.prices.copy();prices.iloc[10] = value
            with self.subTest(value=value),self.assertRaises(ValueError):prepare_prices(prices)

    def test_small_contribution_milestone_does_not_construct_out_of_range_date(self):
        text = milestone_status(5,.01,120,80000,pd.Timestamp('2026-08-22'),True)
        self.assertIn('more than 60 years',text)

    def test_finite_horizon_can_be_active_or_completed(self):
        active = run_plan(self.prices.index[0],1200,0,prices=self.prices,still_buying=False,stop_after_yrs=20)
        self.assertTrue(active.attrs['still_contributing'])
        finished = run_plan(self.prices.index[0],1200,0,prices=self.prices,still_buying=False,stop_after_yrs=.1)
        self.assertFalse(finished.attrs['still_contributing'])
        self.assertLess(finished.attrs['buy_dates'][-1],finished.attrs['stop_date'])
        status = milestone_status(5,0,120,80000,active.index[-1],True,active.attrs['stop_date'])
        self.assertIn('beyond the planned contribution horizon',status)

    def test_invalid_budget_and_nonfinite_inputs_are_rejected(self):
        for args in [(100000,1,1,.03),(np.inf,.1,.1,.03),(100000,.1,.1,np.nan)]:
            with self.subTest(args=args),self.assertRaises(ValueError):validate_allocations(*args)
        for kwargs in [{'annual_btc':np.inf},{'annual_cash':-1},{'cash_apy':np.nan},
                       {'still_buying':False,'stop_after_yrs':np.inf}]:
            args=dict(start=self.prices.index[0],annual_btc=1200,annual_cash=0,prices=self.prices)
            args.update(kwargs)
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):run_plan(**args)

    def test_cash_only_irr_matches_effective_apy(self):
        plan=run_plan(self.prices.index[0],0,1200,prices=self.prices)
        rate=money_weighted_return(plan.attrs['buy_dates'],plan.attrs['total_contributions'],plan.total_value.iloc[-1],plan.index[-1])
        self.assertAlmostEqual(rate,.03,places=10)
