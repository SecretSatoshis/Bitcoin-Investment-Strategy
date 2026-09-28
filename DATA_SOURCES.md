# Data sources and evidence boundaries

The pipeline preserves source-native frequencies and records every live or cached retrieval in `data/manifests/data_manifest.json`.

| Source | Dataset | Frequency | Important limitation |
|---|---|---:|---|
| [BRK / Bitview](https://bitview.space/api) | BTC price and supply | Daily | Five post-genesis no-block dates are explicitly handled |
| [FRED MEHOINUSA646N](https://fred.stlouisfed.org/series/MEHOINUSA646N) / U.S. Census Bureau | Nominal median U.S. household income | Annual | Current dollars, annual, and published with a lag |

The savings plan reads `price` from the daily table and median household income from the annual one. `supply` is published for market capitalization and to verify the known no-block dates. The wider BRK research catalogue is not part of the public release.

## Redistribution

The [GPL-3.0](LICENSE) license applies to repository code and original prose, not automatically to third-party datasets. Data retain the terms of their upstream publishers. Before redistributing a fork or mirror, review the current terms for BRK and FRED. FRED series sourced from the U.S. Census Bureau are U.S. government works, but FRED's own terms of use govern the delivery.

## Historical data rules

- The canonical as-of date is the previous completed UTC day.
- One BRK price request serves the notebook; `price_close` is published as canonical column `price`.
- The no-block dates from 2009-01-04 through 2009-01-08 are expected source gaps in `supply`.
- Where flow series are built (the research catalogue, not the public release), daily flows are differences of cumulative observations, not sums of rolling 24-hour windows, and the observation after a gap is differenced from the last valid one — preserving the 700 BTC issued on 2009-01-09.
- Supplemental cached data are never silent: the manifest records `status: cached` and the failed live request class.
