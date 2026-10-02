# Data sources

Everything except the company and government treasuries comes from one
[Bitcoin Report Library](https://github.com/SecretSatoshis/Bitcoin-Report-Library) release, which
fetches it from the publishers below. Each data release's manifest records that release and the
checksums of the files used: `data/manifests/data_manifest.json` for the savings plan and
`data/research/manifests/data_manifest.json` for the supply and demand notebooks.

## Savings plan (`data/`)

| Source | Dataset | Frequency | Limitation |
|---|---|---:|---|
| BRK, via the Report Library | BTC daily close, `price_close` in `master_metrics_data.csv.gz` | Daily | Starts at the first traded price, 2010-08-16 |
| [FRED MEHOINUSA646N](https://fred.stlouisfed.org/series/MEHOINUSA646N) / U.S. Census Bureau, via the Report Library | Nominal median U.S. household income, `us_median_household_income_usd` in `annual_reference_data.csv` | Annual | Current dollars, published about a year late |

The notebook reads `price` from `data/processed/bitcoin_daily.csv` and income from
`data/processed/median_household_income_annual.csv`.

## Supply and demand (`data/research/`)

| Source | Dataset | Frequency | Limitation |
|---|---|---:|---|
| [BRK](https://bitview.space), via the Report Library | Price, supply, issuance, fees, coin age and holder cohorts, realized price and profit and loss, coin-days destroyed, hash rate, difficulty, funded addresses (`bitcoin_daily.csv`) | Daily | Starts 2010-01-01; priced series start 2010-08-16 |
| [Coin Metrics Labs](https://labs.coinmetrics.io), via the Report Library | Network mining efficiency | Monthly | Carried forward up to a year |
| [World Bank](https://data.worldbank.org) and [Our World in Data](https://ourworldindata.org/grapher/number-of-internet-users), via the Report Library | World internet users and population (`technology_adoption_annual.csv`) | Annual | Internet users before 2005 come from Our World in Data |
| [Crypto.com](https://crypto.com/research), via the Report Library | Estimated bitcoin owners (`bitcoin_owner_estimates.csv`) | Annual | Market-sizing estimates; 2020 and 2021 are half of all crypto owners |
| US spot bitcoin ETF issuers and SEC filings, via the Report Library | Each fund's bitcoin held, shares, NAV and flows, and its quarter-end cost (`etf_daily.csv`, `etf_totals_daily.csv`, `etf_quarterly.csv`) | Daily, quarterly | Checked against each fund's 10-Q and 10-K holdings |
| [CoinGecko](https://www.coingecko.com) public treasury API | Company and government bitcoin holdings | Read when the notebook runs | Not stored; see Redistribution |
| Secret Satoshis | How each government acquired its bitcoin (`data/reference/government_acquisition_types.csv`) | As reviewed | A classification, with a note per entity |

## Rules

- A release covers through the previous completed UTC day, and every series must reach it.
- Both releases come from the Report Library release for exactly that day, and each download must match the checksum in its `release_manifest.json`. Until that release is published the update waits or fails; it never uses an older release.
- The Report Library's `price_close` is published as `price`.
- Income whose newest year is more than three years old stops the release; mining efficiency older than a year stops the supply and demand release.

## Redistribution

The [GPL-3.0](LICENSE) license covers this repository's code and original prose, not third-party data. Data keep their publishers' terms, so review them before redistributing a fork or mirror:

- BRK, the Report Library's on-chain source: BRK's terms.
- FRED: series from the U.S. Census Bureau are U.S. government works, but FRED's terms of use govern how they are delivered.
- Coin Metrics Labs: Creative Commons, non-commercial, with attribution.
- World Bank and Our World in Data: CC BY 4.0.
- Crypto.com and the ETF issuers: their own terms; SEC filings are public.
- CoinGecko: its API terms allow showing its data with the credit "Powered by CoinGecko" but not redistributing it, and allow a local copy only if refreshed at least every 24 hours. The demand notebook reads it when it runs, keeps a copy no older than a day in the ignored `.cache/` folder, and nothing from it is committed.
