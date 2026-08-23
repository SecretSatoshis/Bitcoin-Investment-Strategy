# Data sources and evidence boundaries

The pipeline preserves source-native frequencies and records every live or cached retrieval in `data/manifests/data_manifest.json`.

| Source | Dataset | Frequency | Important limitation |
|---|---|---:|---|
| [BRK / Bitview](https://bitview.space/api) | Price, supply, realized value, mining, holder and age-cohort series | Daily | Some metrics are derived estimates; five post-genesis no-block dates are explicitly handled |
| [FRED MEHOINUSA646N](https://fred.stlouisfed.org/series/MEHOINUSA646N) / U.S. Census Bureau | Nominal median U.S. household income | Annual | Current dollars, annual, and published with a lag |

The savings plan reads `price` from the daily table and median household income from the annual one. The remaining BRK columns are published because they come from the same single retrieval and are covered by the same manifest, not because this notebook consumes them.

## Redistribution

The [GPL-3.0](LICENSE) license applies to repository code and original prose, not automatically to third-party datasets. Data retain the terms of their upstream publishers. Before redistributing a fork or mirror, review the current terms for BRK and FRED. FRED series sourced from the U.S. Census Bureau are U.S. government works, but FRED's own terms of use govern the delivery.

## Historical data rules

- The canonical as-of date is the previous completed UTC day.
- One BRK price request serves the notebook; `price_close` is published as canonical column `price`.
- The no-block dates from 2009-01-04 through 2009-01-08 are expected source gaps. The next cumulative observation is differenced from the last valid observation, preserving the 700 BTC issued on 2009-01-09.
- Non-overlapping daily flows are differences of cumulative observations, not sums of rolling 24-hour windows.
- Supplemental cached data are never silent: the manifest records `status: cached` and the failed live request class.
