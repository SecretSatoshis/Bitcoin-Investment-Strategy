"""Public savings-report exports using the shared savings engine."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from bitcoin_investment_strategy.savings import (
    prepare_prices, run_plan, validate_allocations, money_weighted_return,
)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def records(frame):
    # Pandas serializes unavailable annualized returns to JSON null, not NaN.
    return json.loads(frame.to_json(orient="records", date_format="iso", double_precision=15))


REPORT_FILES = {
    "plan_definition.json", "section3_packet.json", "README.md",
    "cohort_summary.csv", "ytd_summary.csv", "benchmark_results.csv",
    "cohort_paths.csv", "contribution_schedule.csv",
    "current_year_savings.png", "cohort_accumulation.png", "ytd_gains_vs_cash.png",
}


def validate_report_bundle(directory, *, root, require_latest=False):
    """Reject incomplete, mixed-release, stale, or tampered publication bundles."""
    directory, root = Path(directory), Path(root)
    manifest = json.loads((directory / "export_manifest.json").read_text())
    if manifest.get("schema_version") != 1 or set(manifest.get("files", {})) != REPORT_FILES:
        raise ValueError("Savings manifest must contain the complete expected file set")
    if {p.name for p in directory.iterdir()} != REPORT_FILES | {"export_manifest.json"}:
        raise ValueError("Unexpected or missing savings report files")
    for name, metadata in manifest["files"].items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or sha256(path) != metadata["sha256"]:
            raise ValueError(f"Savings checksum mismatch: {name}")
    plan = json.loads((directory / "plan_definition.json").read_text())
    packet = json.loads((directory / "section3_packet.json").read_text())
    if packet.get("schema_version") != 1 or packet.get("plan") != plan:
        raise ValueError("Savings packet and plan disagree")
    provenance = manifest["provenance"]
    if packet.get("provenance") != provenance:
        raise ValueError("Savings packet and manifest provenance disagree")
    source_path = root / "data/manifests/data_manifest.json"
    source = json.loads(source_path.read_text())
    checks = {
        "price_sha256": root / "data/processed/bitcoin_daily.csv",
        "source_manifest_sha256": source_path,
        "engine_sha256": root / "src/bitcoin_investment_strategy/savings.py",
        "exporter_sha256": root / "src/bitcoin_investment_strategy/savings_report.py",
    }
    if any(provenance.get(k) != sha256(p) for k, p in checks.items()):
        raise ValueError("Savings report does not match its source data and code")
    if (provenance.get("source_release_id") != source["release_id"]
            or provenance.get("source_data_end") != source["core_data_end"]
            or provenance.get("price_file") != "data/processed/bitcoin_daily.csv"
            or provenance["price_sha256"] != source["artifacts"][provenance["price_file"]]["sha256"]):
        raise ValueError("Savings report source release disagrees with data manifest")
    cutoff = pd.Timestamp(plan["report_date"])
    if (cutoff.tz is not None or cutoff != cutoff.normalize()
            or cutoff > pd.Timestamp(source["core_data_end"])
            or cutoff >= pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
            or (require_latest and str(cutoff.date()) != source["core_data_end"])):
        raise ValueError("Savings report cutoff is invalid or stale")
    status = "quarter_end" if cutoff.is_quarter_end else "interim"
    if (manifest["report_date"] != plan["report_date"]
            or manifest["snapshot_status"] != status or plan["snapshot_status"] != status
            or plan["is_quarter_end"] != bool(cutoff.is_quarter_end)):
        raise ValueError("Savings report date or quarter-end status disagrees")
    for name in ("cohort_summary", "ytd_summary", "benchmark_results"):
        table = pd.read_csv(directory / f"{name}.csv")
        encoded = pd.DataFrame(packet[name])
        pd.testing.assert_frame_equal(table, encoded, check_dtype=False, rtol=1e-10, atol=1e-8)
        if (set(table.cohort_year) != set(plan["cohort_years"])
                or not table.report_date.eq(plan["report_date"]).all()):
            raise ValueError("Savings table cohorts or report dates disagree")
    ytd = pd.read_csv(directory / "ytd_summary.csv")
    if not np.allclose(ytd.opening_total_value_usd + ytd.total_contributed_ytd_usd
                       + ytd.total_gain_ytd_usd, ytd.closing_total_value_usd):
        raise ValueError("Savings YTD accounting does not reconcile")
    for name in ("cohort_paths", "contribution_schedule"):
        table = pd.read_csv(directory / f"{name}.csv", parse_dates=["date"])
        if table.empty or table.date.isna().any() or table.date.max() > cutoff:
            raise ValueError("Savings paths or purchases exceed the reporting cutoff")
    return manifest


def build_report(prices, *, as_of=None, cohort_years=None, annual_income=100000,
                 bitcoin_fraction=.1, cash_fraction=.1, cash_apy=.03,
                 cadence="monthly", still_buying=True, stop_after_yrs=None):
    validate_allocations(annual_income, bitcoin_fraction, cash_fraction, cash_apy)
    prices = prepare_prices(prices)
    cutoff = prices.index[-1] if as_of is None else pd.Timestamp(as_of)
    if (pd.isna(cutoff) or cutoff.tz is not None or cutoff != cutoff.normalize()
            or cutoff not in prices.index):
        raise ValueError("Report cutoff must be an observed UTC calendar date in the price release")
    if cutoff >= pd.Timestamp.now(tz="UTC").tz_localize(None).normalize():
        raise ValueError("Report cutoff must be a completed UTC day")
    years = list(range(cutoff.year, cutoff.year - 5, -1)) if cohort_years is None else list(cohort_years)
    if (not years or any(isinstance(y, bool) or not isinstance(y, (int, np.integer)) for y in years)
            or len(set(years)) != len(years) or cutoff.year not in years):
        raise ValueError("Cohort years must be unique integers and include the reporting year")
    years = sorted(map(int, years), reverse=True)
    if any(y < 1 or y > cutoff.year for y in years):
        raise ValueError("Cohort start year must be on or before the report year")
    if pd.Timestamp(min(years), 1, 1) < prices.index[0]:
        raise ValueError("Full price coverage from every cohort's January 1 start is required")
    prices = prices.loc[:cutoff]
    year_start = pd.Timestamp(cutoff.year, 1, 1)
    previous_close = year_start - pd.Timedelta(days=1)
    assumptions = {
        "schema_version": 1, "report_date": str(cutoff.date()),
        "report_year": cutoff.year, "calendar_quarter": cutoff.quarter,
        "is_quarter_end": bool(cutoff.is_quarter_end),
        "snapshot_status": "quarter_end" if cutoff.is_quarter_end else "interim",
        "cutoff_selection": "latest_available_completed_day" if as_of is None else "explicit",
        "ytd_start": str(year_start.date()), "opening_balance_date": str(previous_close.date()),
        "cohort_years": years, "annual_income_usd": float(annual_income),
        "bitcoin_fraction_of_income": float(bitcoin_fraction),
        "cash_fraction_of_income": float(cash_fraction), "cash_apy": float(cash_apy),
        "cadence": cadence, "still_buying": bool(still_buying), "stop_after_yrs": stop_after_yrs,
        "annual_bitcoin_contribution_usd": float(annual_income * bitcoin_fraction),
        "annual_cash_contribution_usd": float(annual_income * cash_fraction),
        "benchmark": "cash_only_same_total_contributions_and_dates",
        "rebalancing": "none; percentages apply to new income contributions",
        "cash_timing": "prior cash earns daily interest; new deposits enter after that day's interest",
        "purchase_timing": "scheduled day's observed daily price",
        "cash_day_basis": 365.25,
        "limitations": ["modeled results, not an actual investor account", "fixed nominal income and cash APY",
                        "no fees, taxes, inflation adjustment, or satoshi rounding"],
    }
    summaries, ytd_rows, benchmark_rows, paths, schedules = [], [], [], [], []
    for year in years:
        start = pd.Timestamp(year, 1, 1)
        args = dict(start=start, cadence=cadence, cash_apy=cash_apy, prices=prices,
                    still_buying=still_buying, stop_after_yrs=stop_after_yrs)
        plan = run_plan(annual_btc=annual_income * bitcoin_fraction,
                        annual_cash=annual_income * cash_fraction, **args)
        cash = run_plan(annual_btc=0, annual_cash=annual_income * (bitcoin_fraction + cash_fraction), **args)
        buys = pd.DatetimeIndex(plan.attrs["buy_dates"])
        if list(buys) != cash.attrs["buy_dates"] or not np.allclose(
                plan.attrs["total_contributions"], cash.attrs["total_contributions"], rtol=1e-12):
            raise ValueError("Benchmark contribution schedule differs from the savings plan")
        final, cf = plan.iloc[-1], cash.iloc[-1]
        pnl = plan.total_value - plan.total_contributed
        raw_ratio = pnl / plan.total_contributed.replace(0, np.nan)
        worst = raw_ratio.idxmin()
        summary = {
            "cohort_year": year, "start_date": str(start.date()), "report_date": str(cutoff.date()),
            "purchases": len(buys), "btc_held": float(final.coins),
            "sats_held": float(final.coins * 1e8), "average_purchase_price_usd": float(final.cost_basis),
            "spot_price_usd": float(final.price),
            "btc_contributed_usd": float(final.btc_contributed),
            "cash_contributed_usd": float(final.cash_contributed),
            "total_contributed_usd": float(final.total_contributed),
            "btc_value_usd": float(final.btc_value), "cash_value_usd": float(final.cash_value),
            "total_value_usd": float(final.total_value),
            "btc_gain_usd": float(final.btc_value - final.btc_contributed),
            "cash_interest_usd": float(final.cash_value - final.cash_contributed),
            "total_gain_usd": float(pnl.iloc[-1]),
            "cash_only_value_usd": float(cf.total_value),
            "advantage_vs_cash_usd": float(final.total_value - cf.total_value),
            "money_weighted_return_annualized": money_weighted_return(
                list(buys), plan.attrs["total_contributions"], float(final.total_value), cutoff),
            "days_below_contributions": int((pnl < -1e-8).sum()),
            "observed_days": len(plan), "worst_vs_contributions_date": str(worst.date()),
            "worst_gain_to_contributions_ratio": float(raw_ratio.loc[worst]),
            "still_contributing": bool(plan.attrs["still_contributing"]),
        }
        summaries.append(summary)
        opening = plan.loc[previous_close] if year < cutoff.year else pd.Series(0., index=plan.columns)
        cash_opening = float(cash.loc[previous_close, "total_value"]) if year < cutoff.year else 0.
        btc_deposits = float(final.btc_contributed - opening.btc_contributed)
        cash_deposits = float(final.cash_contributed - opening.cash_contributed)
        deposits = btc_deposits + cash_deposits
        btc_gain = float(final.btc_value - opening.btc_value - btc_deposits)
        cash_gain = float(final.cash_value - opening.cash_value - cash_deposits)
        benchmark_gain = float(cf.total_value - cash_opening - deposits)
        ytd_rows.append({
            "cohort_year": year, "period_start": str(year_start.date()), "report_date": str(cutoff.date()),
            "opening_btc_held": float(opening.coins), "btc_accumulated_ytd": float(final.coins - opening.coins),
            "closing_btc_held": float(final.coins), "opening_btc_value_usd": float(opening.btc_value),
            "opening_cash_value_usd": float(opening.cash_value), "opening_total_value_usd": float(opening.total_value),
            "btc_contributed_ytd_usd": btc_deposits, "cash_contributed_ytd_usd": cash_deposits,
            "total_contributed_ytd_usd": deposits, "btc_gain_ytd_usd": btc_gain,
            "cash_interest_ytd_usd": cash_gain, "total_gain_ytd_usd": btc_gain + cash_gain,
            "closing_total_value_usd": float(final.total_value),
            "cash_only_opening_value_usd": cash_opening, "cash_only_closing_value_usd": float(cf.total_value),
            "cash_only_gain_ytd_usd": benchmark_gain,
            "incremental_advantage_ytd_usd": btc_gain + cash_gain - benchmark_gain,
        })
        for period, opening_plan, opening_cash, contributed in [
            ("since_start", 0., 0., float(final.total_contributed)),
            ("ytd", float(opening.total_value), cash_opening, deposits),
        ]:
            pg, cg = float(final.total_value) - opening_plan - contributed, float(cf.total_value) - opening_cash - contributed
            benchmark_rows.append({"cohort_year": year, "period": period, "report_date": str(cutoff.date()),
                "plan_opening_value_usd": opening_plan, "cash_only_opening_value_usd": opening_cash,
                "contributions_usd": contributed, "plan_closing_value_usd": float(final.total_value),
                "cash_only_closing_value_usd": float(cf.total_value), "plan_gain_usd": pg,
                "cash_only_gain_usd": cg, "gain_advantage_usd": pg - cg})
        path = plan.rename(columns={"coins": "btc_held", "price": "spot_price_usd", "cost_basis": "average_purchase_price_usd",
            **{k: k + "_usd" for k in ["btc_value", "cash_value", "btc_contributed", "cash_contributed", "total_value", "total_contributed"]}}).copy()
        path.attrs = {}
        path["cohort_year"] = year
        path["cash_only_value_usd"] = cash.total_value
        path["gain_usd"] = pnl
        path["advantage_vs_cash_usd"] = plan.total_value - cash.total_value
        paths.append(path.reset_index())
        for day, btc_amount, cash_amount in zip(buys, plan.attrs["btc_contributions"], plan.attrs["cash_contributions"]):
            schedules.append({"cohort_year": year, "date": day, "btc_contribution_usd": btc_amount,
                "cash_contribution_usd": cash_amount, "total_contribution_usd": btc_amount + cash_amount,
                "purchase_price_usd": float(prices.loc[day]), "btc_bought": btc_amount / float(prices.loc[day]),
                "cash_only_contribution_usd": btc_amount + cash_amount})
    return assumptions, {
        "cohort_summary": pd.DataFrame(summaries), "ytd_summary": pd.DataFrame(ytd_rows),
        "benchmark_results": pd.DataFrame(benchmark_rows), "cohort_paths": pd.concat(paths, ignore_index=True),
        "contribution_schedule": pd.DataFrame(schedules),
    }


def render_charts(assumptions, tables, directory):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    stamp = assumptions["report_date"]
    label = "Quarter-end" if assumptions["is_quarter_end"] else "Interim snapshot"
    year = assumptions["report_year"]
    paths = tables["cohort_paths"]
    current = paths[paths.cohort_year == year]
    money = FuncFormatter(lambda v, _: f"${v:,.0f}")
    figures = []
    with plt.rc_context({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False}):
        fig, ax = plt.subplots(figsize=(11, 5.5), layout="constrained")
        for col, name, color, style in [
            ("total_value_usd", "Bitcoin + cash savings", "#F7931A", "-"),
            ("cash_only_value_usd", "Equivalent cash-only plan", "#2E8B57", "-"),
            ("total_contributed_usd", "Total contributions", "#555555", "--"),
        ]:
            ax.plot(current.date, current[col], label=name, color=color, linestyle=style, linewidth=2)
        ax.set(title=f"Starting in {year}: savings value and contributions\n{label} through {stamp}", ylabel="Savings value (USD)")
        ax.yaxis.set_major_formatter(money); ax.legend(); ax.grid(alpha=.2)
        figures.append(("current_year_savings.png", fig))
        fig, ax = plt.subplots(figsize=(11, 5.5), layout="constrained")
        for cohort, part in paths.groupby("cohort_year", sort=True):
            ax.plot(part.date, part.btc_held, label=f"Started {cohort}", linewidth=2)
        ax.set(title=f"Bitcoin accumulated by starting cohort\n{label} through {stamp}", ylabel="Bitcoin held (BTC)")
        ax.legend(); ax.grid(alpha=.2)
        fig.supxlabel("Same annual contribution rule; earlier starters contributed for longer", fontsize=9)
        figures.append(("cohort_accumulation.png", fig))
        ytd = tables["ytd_summary"].sort_values("cohort_year")
        fig, ax = plt.subplots(figsize=(11, 5.5), layout="constrained")
        x = np.arange(len(ytd))
        ax.bar(x - .18, ytd.total_gain_ytd_usd, .36, label="Bitcoin + cash savings", color="#F7931A")
        ax.bar(x + .18, ytd.cash_only_gain_ytd_usd, .36, label="Equivalent cash-only plan", color="#2E8B57")
        ax.set_xticks(x, ytd.cohort_year.astype(str)); ax.yaxis.set_major_formatter(money)
        ax.axhline(0, color="#555555", linewidth=.8)
        ax.set(title=f"{year} investment gains and losses, excluding contributions\n{label} through {stamp}", xlabel="Cohort starting year", ylabel="YTD gain / loss (USD)")
        ax.legend(); ax.grid(axis="y", alpha=.2)
        fig.supxlabel("Dollar gains reflect different opening balances; this is not a return ranking", fontsize=9)
        figures.append(("ytd_gains_vs_cash.png", fig))
        for filename, fig in figures:
            fig.savefig(directory / filename, dpi=160, facecolor="white")
            plt.close(fig)


EXPORT_NOTES = """# Section 3 savings data

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
"""


def export_report(root, *, output_dir=None, **settings):
    root = Path(root)
    data_path = root / "data/processed/bitcoin_daily.csv"
    manifest_path = root / "data/manifests/data_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    digest = sha256(data_path)
    if digest != manifest["artifacts"]["data/processed/bitcoin_daily.csv"]["sha256"]:
        raise ValueError("Savings price input does not match its release manifest")
    data = pd.read_csv(data_path, parse_dates=["date"]).set_index("date")
    if str(data.index.max().date()) != manifest["core_data_end"]:
        raise ValueError("Savings release coverage disagrees with its manifest")
    assumptions, tables = build_report(data.price, **settings)
    provenance = {
        "source_release_id": manifest["release_id"], "source_data_end": manifest["core_data_end"],
        "price_file": str(data_path.relative_to(root)), "price_sha256": digest,
        "source_manifest_sha256": sha256(manifest_path),
        "engine_sha256": sha256(root / "src/bitcoin_investment_strategy/savings.py"),
        "exporter_sha256": sha256(__file__),
    }
    destination = Path(output_dir) if output_dir is not None else root / "outputs/savings/latest"
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    with tempfile.TemporaryDirectory(prefix=".building-", dir=parent) as tmp:
        stage = Path(tmp)
        for name, table in tables.items():
            table.to_csv(stage / f"{name}.csv", index=False, date_format="%Y-%m-%d", float_format="%.15g")
        (stage / "plan_definition.json").write_text(json.dumps(assumptions, indent=2, allow_nan=False) + "\n")
        packet = {"schema_version": 1, "plan": assumptions, "provenance": provenance,
                  **{k: records(tables[k]) for k in ["cohort_summary", "ytd_summary", "benchmark_results"]},
                  "supporting_files": ["cohort_paths.csv", "contribution_schedule.csv", "README.md"],
                  "visuals": ["current_year_savings.png", "cohort_accumulation.png", "ytd_gains_vs_cash.png"]}
        (stage / "section3_packet.json").write_text(json.dumps(packet, indent=2, allow_nan=False) + "\n")
        (stage / "README.md").write_text(EXPORT_NOTES)
        render_charts(assumptions, tables, stage)
        exported_manifest = {"schema_version": 1, "run_id": run_id,
            "report_date": assumptions["report_date"], "snapshot_status": assumptions["snapshot_status"],
            "provenance": provenance, "files": {
                p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
                for p in sorted(stage.iterdir()) if p.is_file()}}
        (stage / "export_manifest.json").write_text(json.dumps(exported_manifest, indent=2) + "\n")
        # Build and validate completely before replacing the latest view.
        validate_report_bundle(stage, root=root)
        previous = parent / f".previous-{run_id}"
        if destination.exists():
            destination.rename(previous)
        try:
            stage.rename(destination)
        except BaseException:
            if previous.exists():
                previous.rename(destination)
            raise
        if previous.exists():
            shutil.rmtree(previous)
    return destination, assumptions, tables
