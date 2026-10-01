# Data sources

Every release records each source's retrieval, and whether a saved copy stood in for a failed fetch, in `data/manifests/data_manifest.json`.

| Source | Dataset | Frequency | Limitation |
|---|---|---:|---|
| [Bitcoin Report Library](https://github.com/SecretSatoshis/Bitcoin-Report-Library) (BRK data) | BTC daily close, `price_close` in `master_metrics_data.csv.gz` | Daily | Starts at the first traded price, 2010-08-16 |
| [FRED MEHOINUSA646N](https://fred.stlouisfed.org/series/MEHOINUSA646N) / U.S. Census Bureau | Nominal median U.S. household income | Annual | Current dollars, published about a year late |

The notebook reads `price` from `data/processed/bitcoin_daily.csv` and income from `data/processed/median_household_income_annual.csv`.

## Rules

- A release covers through the previous completed UTC day, and every series must reach it.
- The price comes from the Report Library release for exactly that day, and the download must match the checksum in its `release_manifest.json`. Until that release is published the update waits or fails; it never uses an older price. The manifest records the Report Library release it used.
- The Report Library's `price_close` is published as `price`.
- If FRED fails, the release reuses its saved copy only when the previous manifest verifies it and its newest year is at most three years old; the manifest then records `status: cached`. A changed FRED format stops the release instead.

## Redistribution

The [GPL-3.0](LICENSE) license covers this repository's code and original prose, not third-party data. Data keep their publishers' terms, so review BRK's (the Report Library's upstream source) and FRED's current terms before redistributing a fork or mirror. FRED series from the U.S. Census Bureau are U.S. government works, but FRED's terms of use govern how they are delivered.
