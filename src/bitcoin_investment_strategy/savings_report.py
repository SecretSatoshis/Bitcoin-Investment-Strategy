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
    "cohort_comparison.png", "cohort_comparison.svg", "current_year_savings.png", "current_year_savings.svg",
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


def render_cohort_comparison(assumptions, summary):
    """Presentation-sized table using the Secret Satoshis website brand system."""
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import Rectangle

    fonts = Path(__file__).parent / "assets/fonts"
    mono = FontProperties(fname=fonts / "JetBrainsMono-400.ttf")
    medium = FontProperties(fname=fonts / "JetBrainsMono-600.ttf")
    display = FontProperties(fname=fonts / "Syne-700.ttf")
    bg, surface, alternate = "#08080c", "#0e0e16", "#13131d"
    primary, secondary, accent, border = "#e4e4ef", "#9090a8", "#F7931A", "#2a2a42"
    # Embed glyph paths in SVG so slides render faithfully without installed fonts.
    with plt.rc_context({"svg.fonttype": "path", "svg.hashsalt": "secret-satoshis-savings"}):
        fig = plt.figure(figsize=(16, 9), facecolor=bg)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set(xlim=(0, 1), ylim=(0, 1))
        ax.axis("off")

        def text(x, y, label, size=12, color=primary, font=mono, align="left", **kwargs):
            ax.text(x, y, label, fontsize=size, color=color, fontproperties=font,
                    ha=align, va="center", **kwargs)

        left, right = .045, .955
        ax.add_patch(Rectangle((left, .927), .007, .017, color=accent, linewidth=0))
        text(left + .018, .935, "SECRET SATOSHIS", 12, font=medium)
        text(right, .935, "BITCOIN SAVINGS STRATEGY", 10, secondary, align="right")
        ax.plot([left, right], [.90, .90], color=border, linewidth=.8)
        text(left, .841, "The savings experience", 30, font=display)
        income = assumptions["annual_income_usd"]
        btc_share = assumptions["bitcoin_fraction_of_income"]
        cash_share = assumptions["cash_fraction_of_income"]
        cash_rate = f"{assumptions['cash_apy'] * 100:g}%"
        text(left, .785, f"Family income: ${income:,.0f} / year  ·  {btc_share:.0%} to Bitcoin  ·  {cash_share:.0%} to USD savings", 12)
        text(left, .739, "Cohort comparison  /  Since each January 1 start", 10, secondary)
        status = "Quarter-end" if assumptions["is_quarter_end"] else "Interim"
        stamp = pd.Timestamp(assumptions["report_date"]).strftime("%d %b %Y").lstrip("0")
        text(right, .739, f"{status}  ·  {stamp}", 10, secondary, align="right")

        widths = np.array([.06, .115, .12, .11, .11, .125, .115, .12, .125])
        edges = left + np.r_[0, np.cumsum(widths)] * (right - left)
        columns = ["cohort_year", "total_contributed_usd", "btc_held", "btc_value_usd",
                   "cash_value_usd", "total_value_usd", "total_gain_usd",
                   "cash_only_value_usd", "advantage_vs_cash_usd"]
        headings = ["Start\nyear", "USD\ncontributed", "BTC\naccumulated", "BTC value\nUSD",
                    "USD\naccumulated", "Savings plan\nvalue · USD", "Total gain /\nloss · USD",
                    f"Cash only\n@ {cash_rate} · USD", "BTC surplus vs\ncash only · USD"]
        header_top, header_bottom, bottom = .70, .58, .28
        ax.add_patch(Rectangle((left, header_bottom), right-left, header_top-header_bottom,
                               facecolor=surface, linewidth=0))
        ax.plot([left, right], [header_top, header_top], color=accent, linewidth=1.2)
        text(left + .010, .677, "SAVINGS PLAN", 9, secondary, medium)
        text((edges[7] + right) / 2, .677, "CASH-ONLY COMPARISON", 9, accent, medium, "center")
        ax.plot([left, right], [.653, .653], color=border, linewidth=.5)
        for c, heading in enumerate(headings):
            text(edges[c]+.010 if c == 0 else edges[c+1]-.010, .617, heading, 9,
                 accent if c == 5 else secondary, medium,
                 "left" if c == 0 else "right", linespacing=1.6)
        summary = summary.sort_values("cohort_year", ascending=False)
        height = (header_bottom-bottom) / len(summary)
        for r, (_, row) in enumerate(summary.iterrows()):
            top = header_bottom-r*height
            current = int(row.cohort_year) == assumptions["report_year"]
            ax.add_patch(Rectangle((left, top-height), right-left, height,
                                   facecolor="#211a12" if current else alternate if r % 2 else surface,
                                   linewidth=0))
            if current:
                ax.add_patch(Rectangle((left, top-height), .0025, height, facecolor=accent, linewidth=0))
            ax.plot([left, right], [top-height, top-height], color=border, linewidth=.5)
            for c, col in enumerate(columns):
                value = row[col]
                label = (str(int(value)) if c == 0 else f"{value:.6f}" if c == 2 else
                         f"−${abs(value):,.0f}" if value < 0 else
                         f"+${value:,.0f}" if c in (6, 8) and value > 0 else f"${value:,.0f}")
                text(edges[c]+.010 if c == 0 else edges[c+1]-.010, top-height/2,
                     label, 12, accent if c == 5 or (c == 0 and current) else primary,
                     medium if c in (0, 5) else mono, "left" if c == 0 else "right")
        # Thin separators distinguish holdings from combined results without a heavy grid.
        for c in (3, 5, 7):
            ax.plot([edges[c], edges[c]], [bottom, header_top], color=border, linewidth=.6)

        text(left, .227, "READING THE TABLE", 9, accent, medium)
        text(left, .188, "USD contributed = Bitcoin + cash deposits.", 9, secondary)
        text(left, .154, "USD accumulated = cash balance including interest.", 9, secondary)
        text(left, .120, "Plan value = BTC value + accumulated cash.", 9, secondary)
        text(.54, .188, "Gain / loss = plan value − total contributions.", 9, secondary)
        text(.54, .154, "Surplus = plan value − matched cash-only balance.", 9, secondary)
        text(.54, .120, f"Cash only = same total deposits earning {cash_rate} APY.", 9, secondary)
        ax.plot([left, right], [.081, .081], color=border, linewidth=.8)
        text(left, .045, "Source: Secret Satoshis · Earlier cohorts saved for longer · USD rounded.", 8, secondary)
        text(right, .045, "Modeled · Nominal USD · Excludes fees / taxes", 8, secondary, align="right")
    return fig


def render_current_year_savings(assumptions, current):
    """Branded 16:9 savings path with matching endpoint summaries and legend."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    fonts = Path(__file__).parent / "assets/fonts"
    mono = FontProperties(fname=fonts / "JetBrainsMono-400.ttf")
    medium = FontProperties(fname=fonts / "JetBrainsMono-600.ttf")
    display = FontProperties(fname=fonts / "Syne-700.ttf")
    bg, primary, secondary = "#08080c", "#e4e4ef", "#9090a8"
    accent, border, cash_color = "#F7931A", "#2a2a42", "#B0A5D8"
    fig = plt.figure(figsize=(16, 9), facecolor=bg)
    shell = fig.add_axes([0, 0, 1, 1])
    shell.set(xlim=(0, 1), ylim=(0, 1))
    shell.axis("off")

    def text(x, y, label, size=12, color=primary, font=mono, align="left"):
        shell.text(x, y, label, fontsize=size, color=color, fontproperties=font,
                   ha=align, va="center")

    left, right = .045, .955
    year = assumptions["report_year"]
    cash_rate = f"{assumptions['cash_apy'] * 100:g}%"
    shell.add_patch(Rectangle((left, .949), .007, .017, color=accent, linewidth=0))
    text(left + .018, .957, "SECRET SATOSHIS", 12, font=medium)
    text(right, .957, "BITCOIN SAVINGS STRATEGY", 10, secondary, align="right")
    shell.plot([left, right], [.928, .928], color=border, linewidth=.8)
    text(left, .884, f"Starting in {year}", 30, font=display)
    text(left, .830, f"Family income: ${assumptions['annual_income_usd']:,.0f} / year  ·  "
         f"{assumptions['bitcoin_fraction_of_income']:.0%} to Bitcoin  ·  "
         f"{assumptions['cash_fraction_of_income']:.0%} to USD savings", 12)
    text(left, .790, f"Savings value and contributions  /  {assumptions['cadence'].capitalize()} deposits", 10, secondary)
    status = "Quarter-end" if assumptions["is_quarter_end"] else "Interim"
    stamp = pd.Timestamp(assumptions["report_date"]).strftime("%d %b %Y").lstrip("0")
    text(right, .790, f"{status}  ·  {stamp}", 10, secondary, align="right")
    shell.plot([left, right], [.762, .762], color=accent, linewidth=1.2)

    series = [
        ("total_value_usd", "Bitcoin + USD savings", accent, "-"),
        ("cash_only_value_usd", f"Cash only @ {cash_rate} APY", cash_color, "-"),
        ("total_contributed_usd", "Total USD contributed", secondary, "--"),
    ]
    current = current.sort_values("date")
    # Move endpoint summaries into a side rail so the plot can be much taller.
    text(.805, .731, "AT REPORT DATE", 9, secondary, medium)
    for i, (col, name, color, style) in enumerate(series):
        y = .683 - i * .165
        shell.plot([.805, .833], [y, y], color=color, linestyle=style, linewidth=2)
        text(.805, y-.035, name, 9, secondary)
        text(.805, y-.089, f"${current.iloc[-1][col]:,.0f}", 23, color, display)
        if i < 2:
            shell.plot([.805, right], [y-.127, y-.127], color=border, linewidth=.6)

    ax = fig.add_axes([.10, .18, .66, .55], facecolor=bg)
    for col, name, color, style in series:
        ax.plot(current.date, current[col], color=color, linestyle=style,
                linewidth=2.6 if col == "total_value_usd" else 1.7,
                drawstyle="steps-post" if col == "total_contributed_usd" else "default",
                zorder=3 if col == "total_value_usd" else 2)
        ax.scatter(current.date.iloc[-1], current[col].iloc[-1], color=color,
                   s=24, zorder=4, edgecolors=bg, linewidths=.7)
    ax.set_xlim(pd.Timestamp(year, 1, 1), pd.Timestamp(year, 12, 31))
    ax.set_ylim(0, current[[s[0] for s in series]].to_numpy().max()*1.04)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6, min_n_ticks=3))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.tick_params(axis="both", colors=secondary, length=0, pad=10)
    for tick in [*ax.get_xticklabels(), *ax.get_yticklabels()]:
        tick.set_fontproperties(mono)
        tick.set_fontsize(10)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(False, axis="x")
    ax.grid(axis="y", color=border, linewidth=.6)
    text(left, .742, "USD", 9, secondary)
    text(left, .112, "Cash-only comparison receives the same total deposits on the same dates.", 9, secondary)
    text(right, .112, "Balances include contributions and gains / losses.", 9, secondary, align="right")
    shell.plot([left, right], [.081, .081], color=border, linewidth=.8)
    text(left, .045, f"Source: Secret Satoshis savings model · Cash earns {cash_rate} APY · USD rounded.", 8, secondary)
    text(right, .045, "Modeled · Nominal USD · Excludes fees / taxes", 8, secondary, align="right")
    return fig


def render_charts(assumptions, tables, directory):
    import matplotlib.pyplot as plt
    year = assumptions["report_year"]
    paths = tables["cohort_paths"]
    current = paths[paths.cohort_year == year]
    with plt.rc_context({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False}):
        comparison = render_cohort_comparison(assumptions, tables["cohort_summary"])
        comparison.savefig(directory / "cohort_comparison.png", dpi=200, facecolor=comparison.get_facecolor())
        with plt.rc_context({"svg.fonttype": "path", "svg.hashsalt": "secret-satoshis-savings"}):
            comparison.savefig(directory / "cohort_comparison.svg", facecolor=comparison.get_facecolor())
        plt.close(comparison)
        current_chart = render_current_year_savings(assumptions, current)
        current_chart.savefig(directory / "current_year_savings.png", dpi=200, facecolor=current_chart.get_facecolor())
        with plt.rc_context({"svg.fonttype": "path", "svg.hashsalt": "secret-satoshis-savings"}):
            current_chart.savefig(directory / "current_year_savings.svg", facecolor=current_chart.get_facecolor())
        plt.close(current_chart)


EXPORT_NOTES = """# Section 3 savings data

Read `section3_packet.json` first. It contains the assumptions, provenance, cohort
totals, YTD attribution and cash comparisons. CSVs preserve numerical detail; the
daily paths and contribution schedule support charts and checking.

`cohort_comparison.png` is the main cohort comparison: start year, total USD
contributed, BTC accumulated, BTC value, cash accumulated (including interest),
combined savings-plan value, total gain/loss, cash-only balance at the assumed APY,
and surplus versus cash only. The last two columns form the cash-only comparison.
The subtitle displays the modeled family income and contribution allocations.
All values are since start through the common report date, sourced from
`cohort_summary.csv`. The savings visuals are the cohort comparison and the
current-year savings chart; YTD data remains available in CSV and JSON form.
The branded table is a 3200 × 1800 PNG (16:9); `cohort_comparison.svg` is the
matching scalable presentation export, with font outlines embedded.
`current_year_savings.png` and `.svg` use the same branded 16:9 format, plotting
the current-year plan, matched cash-only balance, and total contributions.
The legend displays the closing values through the stated report date.

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
                  "visuals": ["cohort_comparison.png", "cohort_comparison.svg", "current_year_savings.png", "current_year_savings.svg"]}
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
