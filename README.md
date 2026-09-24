# Bitcoin Investment Strategy

A Bitcoin savings-plan notebook. [`bitcoin_savings_plan.ipynb`](notebooks/bitcoin_savings_plan.ipynb) is the companion to [**Should I buy bitcoin?**](https://newsletter.secretsatoshis.com/p/should-i-buy-bitcoin) — the post sets out the framework; the notebook is that framework in runnable form.

Set your own contribution, cadence and start date, run it, and it reports cost basis against market price, sats accumulated, portfolio value, and how the plan compares with holding cash over the same period.

## Pipeline

```text
BRK / Bitview        FRED / U.S. Census
      ↓                      ↓
        scripts/update_data.py
                 ↓
raw snapshots → validation and transforms → processed release + manifest
                                                   ↓
                                          savings plan notebook
```

The updater retrieves each upstream metric once. Daily price and network series live in `data/processed/bitcoin_daily.csv`; median household income is annual and stays separate because it has a different frequency and revision cycle.

All required daily metrics must reach the requested cutoff; the updater rejects a shorter release. Income observations must be nonempty, finite, positive and unique by completed calendar year. Cached inputs must match the previous release manifest before reuse.

Every published data input is covered by `data/manifests/data_manifest.json`, which records the release ID, retrieval time, coverage, source status and SHA-256 checksum. The notebook verifies its inputs against that manifest before calculating anything.

The notebook uses the tested savings engine in `src/bitcoin_investment_strategy/savings.py`. Purchases require an observed positive price on every trading day; leading pre-market zero or missing prices are excluded. Combined allocations cannot exceed income. Contribution status follows the plan's stop date, and milestone estimates respect that horizon and avoid unsupported distant dates.

## Reproduce locally

Python 3.12 is the supported runtime.

```bash
uv sync --locked

uv run --no-sync python scripts/update_data.py
uv run --no-sync python scripts/validate_data.py
uv run --no-sync python scripts/execute_notebooks.py
uv run --no-sync python scripts/validate_data.py
uv run --no-sync python scripts/validate_savings_report.py
uv run --no-sync python -m unittest discover -s tests -v
```

Use `--as-of YYYY-MM-DD` with `scripts/update_data.py` to request a specific completed UTC date. The default is the previous completed UTC day.

Neither source needs an API key. FRED is a slow annual series and occasionally stalls;
when a transient live request fails, the updater can fall back to the committed verified
snapshot and records `status: cached` in the manifest. The fallback is refused if its
latest observation is more than three years behind the requested release year, and an
upstream schema change fails loudly instead of silently freezing the dataset.

## Daily publication

`.github/workflows/pipeline-health.yml` runs daily at 07:17 UTC (subject to GitHub
scheduling delays) and can also be started manually. Each scheduled or manual run:

1. runs the regression contracts;
2. refreshes both sources once;
3. validates the release;
4. executes the notebook;
5. validates the data again and checks the savings-report bundle and generated paths;
6. uploads the exact public data, manifests, executed notebook, and savings-report
   bundle as a workflow artifact retained for 30 days; and
7. on `main`, commits those validated outputs back to `main` in a separate publish job.

Pull requests run regression tests only. Manual runs on other branches do not
publish. The build job has read-only repository access; only the separate publish
job receives write permission. It restores an exact allowlist of hash-verified
files from the successful build. Research notebooks and local research data are
excluded. A concurrent change to `main` causes the push to fail safely; rerun the
workflow against the new revision instead of overwriting or rebasing generated data.

A critical fetch, validation, or notebook failure stops publication and leaves the
last committed release available. A concurrency lock prevents overlapping runs on
the same branch. Repository branch rules must permit the workflow's bot to commit
these updates.

## Quarterly newsletter inputs

Notebook Section 14 uses the public exporter in
`src/bitcoin_investment_strategy/savings_report.py` and the same tested savings
engine as the personal plan. It exports the reporting-year starter cohort and
the previous four cohorts using the contribution assumptions from Section 1.
The personal `PLAN_START` does not change those January 1 cohort starts.

The stable public bundle lives at [`outputs/savings/latest/`](outputs/savings/latest/).
Start with `section3_packet.json`: assumptions, source/code checksums, since-start
results, YTD attribution, and matched cash comparisons. Supporting CSVs contain
daily paths and purchase schedules. Three PNG charts accompany the data; their
editorial selection can be decided independently of the calculations.

Every daily publication replaces the latest bundle **in the same commit** as its
data and executed notebook. Git history preserves prior snapshots. A quarterly
newsletter must pin a commit whose bundle `report_date` equals the intended
quarter-end and whose `snapshot_status` is `quarter_end`; it must not use a later
live `main` bundle or relabel an interim run. Read the complete bundle from that
same commit and verify its export manifest. This is a savings-data producer, not
the quarterly newsletter writing workflow.

If a quarter-end run was missed, regenerate an explicit `REPORT_AS_OF` snapshot
from data covering that date and validate it before handing it to the newsletter.
The daily publication validator requires the bundle to match the data release's
latest date. The committed notebook should therefore keep `REPORT_AS_OF = None`
and `REPORT_COHORT_YEARS = None`; historical reconstruction is a separate local task.

Running the notebook also updates this tracked bundle locally. Older dated local
exports under `outputs/savings/<date>/<run-id>/` remain ignored. The calculation
definitions and limitations are included in every bundle's `README.md`.

## Repository layout

```text
notebooks/       the savings plan notebook
data/raw/        one stable snapshot per upstream dataset
data/processed/  canonical notebook inputs
data/manifests/  source registry, column dictionary and release manifest
src/             fetch, transformation and validation library
scripts/         update, validation and execution entry points
tests/           release and notebook-consumer contracts
outputs/savings/latest/  public newsletter data and chart bundle
```

## Scope and risk

This notebook is a research and educational tool, not investment advice. Results are nominal, frictionless and pre-tax unless the notebook explicitly states otherwise. Past accumulation outcomes do not predict future ones. See [`DATA_SOURCES.md`](DATA_SOURCES.md) for source-specific caveats.

## License

[GPL-3.0](LICENSE) for the code and original prose in this repository.

The license does not extend to third-party datasets. Data retain the terms of their upstream publishers — see [`DATA_SOURCES.md`](DATA_SOURCES.md) before redistributing a fork or mirror.
