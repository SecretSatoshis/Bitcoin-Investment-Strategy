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
uv run --no-sync python -m unittest discover -s tests -v
```

Use `--as-of YYYY-MM-DD` with `scripts/update_data.py` to request a specific completed UTC date. The default is the previous completed UTC day.

Neither source needs an API key. FRED is a slow annual series and occasionally stalls;
when a transient live request fails, the updater can fall back to the committed verified
snapshot and records `status: cached` in the manifest. The fallback is refused if its
latest observation is more than three years behind the requested release year, and an
upstream schema change fails loudly instead of silently freezing the dataset.

## Pipeline health check

`.github/workflows/pipeline-health.yml` runs every day and can also be started manually. It does not modify the repository — it proves the pipeline still works against the live upstreams. Each run:

1. runs the regression contracts;
2. refreshes both sources once;
3. validates the release;
4. executes the notebook;
5. validates again, and checks that only expected paths changed; and
6. uploads raw and processed data, all manifests, and the notebook as a workflow artifact, so the downloaded release can be validated.

Nothing is committed. The committed data is a dated snapshot, refreshed deliberately rather than automatically; run the commands above locally for current figures. A red run means an upstream changed shape or went away.

A critical BRK failure stops the run. The workflow holds no write permission on the repository, and a concurrency lock prevents overlapping runs.

## Repository layout

```text
notebooks/       the savings plan notebook
data/raw/        one stable snapshot per upstream dataset
data/processed/  canonical notebook inputs
data/manifests/  source registry, column dictionary and release manifest
src/             fetch, transformation and validation library
scripts/         update, validation and execution entry points
tests/           release and notebook-consumer contracts
```

## Scope and risk

This notebook is a research and educational tool, not investment advice. Results are nominal, frictionless and pre-tax unless the notebook explicitly states otherwise. Past accumulation outcomes do not predict future ones. See [`DATA_SOURCES.md`](DATA_SOURCES.md) for source-specific caveats.

## License

[GPL-3.0](LICENSE) for the code and original prose in this repository.

The license does not extend to third-party datasets. Data retain the terms of their upstream publishers — see [`DATA_SOURCES.md`](DATA_SOURCES.md) before redistributing a fork or mirror.
