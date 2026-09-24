# Section 3 savings data

Read `section3_packet.json` first. It contains the assumptions, provenance, cohort
totals, YTD attribution and cash comparisons. CSVs preserve numerical detail; the
daily paths and contribution schedule support charts and checking.

All dollars are nominal USD. BTC quantities are unrounded simulated fractional
coins; sats_held = BTC * 100,000,000, without per-purchase rounding. No fees or taxes.
Fraction and ratio fields use decimals (0.10 = 10%). Annualized money-weighted return
is a since-start annual rate, NOT a YTD return. It is null for windows under 30 days
or where the engine cannot solve it. It is supporting data, not the headline result.

## Accounting

- Since-start gain = closing value minus all contributions.
- YTD opening balances are December 31 closes; a current-year starter opens at zero.
- YTD gain = closing value minus opening value minus contributions made this year.
- BTC gain and cash interest sum to combined gain. Contributions are not gains.
- Both plans receive identical total contributions on identical dates. The cash-only
  scenario earns the same constant APY. It is a modeled alternative, not a bank product.
- `advantage_vs_cash_usd` is the cumulative difference in closing balances.
- `incremental_advantage_ytd_usd` and the YTD benchmark `gain_advantage_usd` measure
  the change in that advantage this year, allowing for different opening balances.
- The annual allocation percentages apply to contributions, with no rebalancing.
- `worst_gain_to_contributions_ratio` is the lowest value/contributions minus one;
  it is NOT a drawdown or a cash-flow-adjusted investment return.
- Dollar gains across cohorts reflect different invested balances and durations.

The manifest hashes every exported artifact plus the selected input and code versions.
The source release may extend beyond report_date; all exported calculations and paths
stop at report_date. An interim snapshot must not be presented as a completed quarter.
