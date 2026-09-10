"""Deterministic savings calculations, independent of notebook presentation."""
import numpy as np
import pandas as pd


def validate_allocations(income, bitcoin_fraction, cash_fraction, cash_apy):
    values = [income, bitcoin_fraction, cash_fraction, cash_apy]
    if not all(np.isfinite(v) for v in values):
        raise ValueError("Income, allocations and APY must be finite numbers")
    if income <= 0 or not 0 < bitcoin_fraction <= 1 or not 0 <= cash_fraction <= 1:
        raise ValueError("Income and allocation percentages are out of range")
    if bitcoin_fraction + cash_fraction > 1 + 1e-12:
        raise ValueError("Total allocations cannot exceed household income")
    if cash_apy <= -1:
        raise ValueError("CASH_APY must be greater than -1")


def prepare_prices(prices):
    if prices is None or prices.empty or not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("A nonempty dated price series is required")
    index = prices.index
    if index.hasnans or index.has_duplicates or index.tz is not None or not index.is_monotonic_increasing or not index.equals(index.normalize()):
        raise ValueError("Price dates must be unique, ordered UTC calendar dates")
    prices = pd.to_numeric(prices, errors="raise")
    if np.isinf(prices).any() or prices.lt(0).any():
        raise ValueError("Prices must be finite and nonnegative before trading begins")
    positive = prices[prices.gt(0)]
    if positive.empty:
        raise ValueError("No positive tradable prices are available")
    prices = prices.loc[positive.index[0]:]
    if not np.isfinite(prices).all() or not prices.gt(0).all():
        raise ValueError("Tradable prices must be finite and positive on every day")
    if not prices.index.equals(pd.date_range(prices.index[0], prices.index[-1], freq="D")):
        raise ValueError("Tradable price history contains missing calendar days")
    return prices


def milestone_status(level, held, annual_btc, spot, as_of, contributing, stop_date=None):
    if not contributing:
        return f"{held/level:.0%} there"
    years = max(level - held, 0) / (annual_btc / spot)
    if stop_date is not None and years * 365.25 > (stop_date - as_of).total_seconds() / 86400:
        return f"{held/level:.0%} there — beyond the planned contribution horizon"
    if not np.isfinite(years) or years >= 60:
        return f"{held/level:.0%} there — more than 60 years at this pace"
    try:
        eta = as_of + pd.Timedelta(days=years * 365.25)
    except (OverflowError, ValueError):
        return f"{held/level:.0%} there — beyond the supported date range"
    return f"{held/level:.0%} there — about {eta:%b %Y} at this pace"


CADENCE_RULE = {"weekly": "W-MON", "biweekly": "2W-MON", "monthly": "MS"}

def annual_buy_count(year, cadence, anchor):
    """Scheduled contributions in a full calendar year on this plan's cadence."""
    if cadence == "monthly":
        return 12
    mondays = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="W-MON")
    step = 7 if cadence == "weekly" else 14
    return int((((mondays - anchor).days % step) == 0).sum())

def run_plan(start, annual_btc, annual_cash, cadence="monthly", cash_apy=0.03,
             prices=None, still_buying=True, stop_after_yrs=None):
    if not all(np.isfinite(v) for v in [annual_btc, annual_cash, cash_apy]):
        raise ValueError("Contributions and APY must be finite")
    if min(annual_btc, annual_cash) < 0 or annual_btc + annual_cash <= 0 or cash_apy <= -1:
        raise ValueError("Invalid contributions or APY")
    if not isinstance(still_buying, (bool, np.bool_)):
        raise ValueError("still_buying must be boolean")
    start = pd.Timestamp(start)
    if pd.isna(start) or start.tz is not None or start != start.normalize():
        raise ValueError("Start must be a UTC calendar date")
    prices = prepare_prices(prices)
    stop_date = None
    # Day-by-day simulation. Buys always use that day's observed price.
    start = max(start, prices.index[0])
    last = prices.index[-1]
    if start > last:
        raise ValueError(
            f"PLAN_START ({start:%Y-%m-%d}) is after the last price date ({last:%Y-%m-%d}). "
            "Set an earlier start date, or refresh the price data."
        )
    if cadence not in CADENCE_RULE:
        raise ValueError(f"BUY_CADENCE must be one of {sorted(CADENCE_RULE)}; got {cadence!r}.")
    buy_dates = list(pd.date_range(start, last, freq=CADENCE_RULE[cadence]))
    if not still_buying:
        if stop_after_yrs is None or not np.isfinite(stop_after_yrs) or stop_after_yrs <= 0:
            raise ValueError("STOP_AFTER_YRS must be positive when STILL_BUYING is False.")
        stop_date = start + pd.Timedelta(days=float(stop_after_yrs) * 365.25)
        buy_dates = [d for d in buy_dates if d < stop_date]
    if not buy_dates:
        raise ValueError("The plan makes no purchases with these settings; check PLAN_START and STOP_AFTER_YRS.")

    # Spread each calendar year's budget across its actual number of scheduled
    # contributions (52/53 weekly or 26/27 biweekly), keeping the annual total exact.
    anchor = buy_dates[0]
    counts = {year: annual_buy_count(year, cadence, anchor)
              for year in {d.year for d in buy_dates}}
    btc_schedule = {d: annual_btc / counts[d.year] for d in buy_dates}
    cash_schedule = {d: annual_cash / counts[d.year] for d in buy_dates}
    daily_rate = (1 + cash_apy) ** (1 / 365.25) - 1
    buys = set(buy_dates)

    coins = cash = btc_in = cash_in = 0.0
    rows = []
    for day in pd.date_range(start, last, freq="D"):
        cash *= (1 + daily_rate)
        if day in buys:
            price = float(prices.loc[day])
            btc_amount, cash_amount = btc_schedule[day], cash_schedule[day]
            coins += btc_amount / price
            btc_in += btc_amount
            cash += cash_amount
            cash_in += cash_amount
        spot = float(prices.loc[day])
        rows.append((day, coins, coins * spot, cash, btc_in, cash_in, spot))

    p = pd.DataFrame(rows, columns=["date", "coins", "btc_value", "cash_value",
                                    "btc_contributed", "cash_contributed", "price"]).set_index("date")
    p["total_value"]       = p["btc_value"] + p["cash_value"]
    p["total_contributed"] = p["btc_contributed"] + p["cash_contributed"]
    # Average price paid so far — the classic DCA cost-basis line.
    p["cost_basis"] = p["btc_contributed"] / p["coins"].replace(0, np.nan)
    p.attrs["stop_date"] = stop_date
    p.attrs["still_contributing"] = stop_date is None or last < stop_date
    p.attrs["buy_dates"] = buy_dates
    p.attrs["btc_contributions"] = [btc_schedule[d] for d in buy_dates]
    p.attrs["cash_contributions"] = [cash_schedule[d] for d in buy_dates]
    p.attrs["total_contributions"] = [btc_schedule[d] + cash_schedule[d] for d in buy_dates]
    return p

def money_weighted_return(dates, amounts, final_value, final_date):
    # The annual rate that turns the contribution stream into the final value. May be negative.
    contributed = float(sum(amounts))
    if not dates or contributed <= 0:
        return np.nan
    elapsed = max((final_date - min(dates)).days, 0) / 365.25
    if elapsed < 30 / 365.25:          # too short for an annual rate to mean anything
        return np.nan
    if final_value <= 0:               # everything lost; the rate is -100%
        return -1.0

    def npv(r):
        return sum(-a * (1 + r) ** ((final_date - d).days / 365.25)
                   for d, a in zip(dates, amounts)) + final_value

    # Bracket wide enough for a plan that multiplied many times over a short window.
    lo, hi = -0.999, 100.0
    if npv(lo) * npv(hi) > 0:
        return np.nan
    for _ in range(300):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0: hi = mid
        else: lo = mid
    return (lo + hi) / 2
