"""Checks and chart helpers shared by the supply and demand notebooks."""
import numpy as np
import pandas as pd

# The brand palette, re-exported for the notebooks.
from ..style import (  # noqa: F401
    BG, BLUE, BORDER, CASH, GREEN, MONO, MONO_MEDIUM, ORANGE, PRIMARY, RED, SECONDARY, apply_theme,
)
from .config import HALVING_DATES

GREY = SECONDARY
# Coin-age bands, youngest to oldest: cool to warm, with every neighbouring pair kept apart
# for the common forms of colour blindness.
AGE_PALETTE = ["#7C9CF0", "#45BFD0", "#6CCB8E", "#F3DA75", ORANGE, "#E05A47"]


def covered_periods(index, code, first, last):
    periods = index.to_period(code)
    return np.asarray((periods.start_time >= pd.Timestamp(first).normalize()) &
                      (periods.end_time.normalize() <= pd.Timestamp(last).normalize()))


# The release publishes ten significant digits, so supply (~2e7 BTC) is exact to 0.01 BTC
# and two published cohorts can miss the published total by up to 0.015 BTC.
COHORT_TOLERANCE_BTC = 0.02


def validate_cohorts(frame, atol=COHORT_TOLERANCE_BTC):
    columns = ['supply', 'lth_supply', 'sth_supply']
    valid = frame['supply'].notna()
    values = frame.loc[valid, columns]
    if values.empty or not np.isfinite(values.to_numpy()).all():
        raise ValueError('Supply cohorts must contain finite observations')
    if values.lt(-atol).any().any():
        raise ValueError('Supply cohorts cannot be negative')
    for name in ['lth_supply', 'sth_supply']:
        if values[name].gt(values.supply + atol).any():
            raise ValueError('A holder cohort exceeds total supply')
    error = (values.lth_supply + values.sth_supply - values.supply).abs()
    if error.gt(atol).any():
        raise ValueError('LTH + STH does not reconcile to total supply')
    for name in frame.columns:
        if name.startswith('utxos_over_') and name.endswith('_old_supply'):
            cohort = frame.loc[valid, name]
            if not np.isfinite(cohort).all() or cohort.lt(-atol).any() or cohort.gt(values.supply + atol).any():
                raise ValueError(f'{name}: invalid cohort stock')
    return float(error.max())


def halving_dates():
    """(n, date, new block reward) for each halving so far, from config.HALVING_DATES."""
    return [(n, pd.Timestamp(date), 50 / 2 ** n) for n, date in enumerate(HALVING_DATES, start=1)]


def forward_change(series, end, last, days=90):
    end, last = pd.Timestamp(end), pd.Timestamp(last)
    target = end + pd.Timedelta(days=days)
    if end >= last:
        return 'still open'
    if target > last:
        return f'pending ({(last - end).days}/{days}d)'
    window = series.reindex(pd.date_range(end, target, freq='D'))
    if not np.isfinite(window).all() or not window.gt(0).all():
        return 'incomplete data'
    return f'{(window.iloc[-1] / window.iloc[0] - 1) * 100:+.0f}%'


# ------------------------------------------------------------ shared chart helpers
# Both notebooks draw with these, so a formatting fix lands in one place.

def usd(x, _=None):
    """Whole dollars; cents below $1, so early log-scale ticks don't all read $0."""
    return f"${x:,.0f}" if x == 0 or abs(x) >= 1 else f"${x:,.2f}"


def thousands(x, _=None):
    return f"{x:,.0f}"


def compact(x, _=None):
    """1_500_000 -> '1.5M'. Keeps large and log axes readable."""
    if x == 0:
        return "0"
    for scale, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(x) >= scale:
            return f"{_trim(x / scale)}{suffix}"
    return f"{x:,.0f}" if abs(x) >= 1 else f"{x:,.2f}"


def _trim(v):
    """One decimal at most, none when it is zero: 17.5, 20, 2.5."""
    return f"{v:,.1f}".removesuffix(".0")


def hashes(x, _=None):
    """Hashes per second with SI prefixes: 1e20 -> '100 EH/s'."""
    if x <= 0:
        return "0"
    for scale, prefix in ((1e21, "Z"), (1e18, "E"), (1e15, "P"), (1e12, "T"), (1e9, "G"),
                          (1e6, "M"), (1e3, "k")):
        if x >= scale:
            return f"{_trim(x / scale)} {prefix}H/s"
    return f"{_trim(x)} H/s"


def log_axis(axis, formatter):
    """Label a log axis's powers of ten, and some of the steps between them when the visible
    range is too narrow for the powers alone to give more than a label or two."""
    from matplotlib.ticker import FuncFormatter

    def between(x, _):
        low, high = sorted(axis.get_view_interval())
        if low <= 0 or x <= 0:
            return ""
        leads = (2, 3, 4, 5, 6, 8) if high / low < 10 else (2, 5) if high / low < 100 else ()
        return formatter(x) if round(x / 10 ** np.floor(np.log10(x))) in leads else ""

    axis.set_major_formatter(FuncFormatter(formatter))
    axis.set_minor_formatter(FuncFormatter(between))


def period_centers(idx, code):
    """Midpoint of each period, so a bar sits over the span it describes.

    Resampling stamps every period at its last day; drawing there puts the bar
    half a period to the right of the data it summarizes.
    """
    periods = idx.to_period(code)
    return periods.start_time + (periods.end_time - periods.start_time) / 2


def price_axis(ax, label="Bitcoin price (USD, log scale)"):
    ax.set_yscale("log"); ax.set_ylabel(label)
    log_axis(ax.yaxis, usd)
    return ax


# ------------------------------------------------------------ data credits
# Each chart names its sources in the Chart Library's "Data Source: BRK" style; licenses
# are listed in each notebook's sources table. CoinGecko's API terms require the exact
# words "Powered by CoinGecko" at 10pt or larger, so it is kept as its own phrase.

BRK = "BRK"
COIN_METRICS = "Coin Metrics Labs"
WORLD_BANK = "World Bank"
OWID = "Our World in Data"
CRYPTO_COM = "Crypto.com"
CLASSIFICATION = "Secret Satoshis classification"
COINGECKO = "Powered by CoinGecko"
ETF_DATASET = "Secret Satoshis ETF dataset"
FOOTER_INCHES = 0.4


def credit_line(sources):
    """'Data Source: BRK · … | Chart and calculations: Secret Satoshis', plus CoinGecko's phrase."""
    data = [source for source in sources if source != COINGECKO]
    parts = [f"Data Source: {' · '.join(data)}"] if data else []
    parts.append("Chart and calculations: Secret Satoshis")
    if COINGECKO in sources:
        parts.append(COINGECKO)
    return "   |   ".join(parts)


HEADER_INCHES = 0.35
WORDMARK = "SECRET SATOSHIS · RESEARCH"


def apply_research_theme():
    """The Secret Satoshis dark chart theme (as the savings notebook), with a faint horizontal grid
    and the brand colours as the default cycle, for every following figure."""
    from cycler import cycler
    import matplotlib.pyplot as plt
    apply_theme()
    plt.rcParams.update({
        "figure.figsize": (15, 6.5),
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": BORDER, "grid.linewidth": 0.6,
        "axes.prop_cycle": cycler(color=[ORANGE, BLUE, GREEN, RED, CASH, SECONDARY]),
        # Partial periods are hatched over a faded bar; light lines keep them legible on the dark ground.
        "hatch.color": PRIMARY,
    })


def finish(fig, title=None, ax=None, sources=()):
    """Lay out the figure with the Secret Satoshis wordmark at the top and the source credit at
    the bottom, then show it."""
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateLocator
    from matplotlib.patches import Rectangle
    if title and ax is not None:
        ax.set_title(title, fontsize=12, pad=12)
    for axis in fig.axes:
        # Slant date labels so they never collide; numeric and category axes stay level.
        if isinstance(axis.xaxis.get_major_locator(), DateLocator):
            for label in axis.get_xticklabels():
                label.set_rotation(30); label.set_horizontalalignment("right")
        # A twin axis (twinx) has no background of its own; its grid would double the first's.
        if not axis.patch.get_visible():
            axis.grid(False)
    height = fig.get_size_inches()[1]
    bottom = FOOTER_INCHES / height if sources else 0
    fig.tight_layout(rect=(0, bottom, 1, 1 - HEADER_INCHES / height))
    middle = 1 - 0.18 / height
    fig.add_artist(Rectangle((0.01, middle - 0.06 / height), 0.0035, 0.12 / height,
                             transform=fig.transFigure, facecolor=ORANGE, edgecolor="none"))
    fig.text(0.017, middle, WORDMARK, fontproperties=MONO_MEDIUM, fontsize=9, color=SECONDARY, va="center")
    if sources:
        fig.text(0.01, 0.012, credit_line(sources), fontproperties=MONO, fontsize=10, color=SECONDARY,
                 ha="left", va="bottom")
    plt.show(); plt.close(fig)


# ------------------------------------------------------------ data-age disclosure

RELEASE_MAX_AGE_DAYS = 7


def release_age_note(core_data_end, now=None, max_age_days=RELEASE_MAX_AGE_DAYS):
    """A warning when the release is older than the refresh budget, else None."""
    end = pd.Timestamp(core_data_end).normalize()
    today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() if now is None else pd.Timestamp(now)
    age = (today - pd.Timedelta(days=1) - end).days
    if age > max_age_days:
        return (f"NOTE: this release ends {end.date()}, {age} days before the last "
                f"completed UTC day. Every 'at cutoff' figure describes {end.date()}, not today. "
                "Refresh with scripts/update_data.py.")
    return None


def snapshot_date_note(as_of, cutoff, label):
    """Disclose holdings snapshots dated after the series cutoff they are compared with."""
    dates = pd.to_datetime(pd.Series(as_of), errors="coerce").dropna()
    cutoff = pd.Timestamp(cutoff).normalize()
    later = dates[dates.dt.normalize() > cutoff]
    if later.empty:
        return None
    return (f"NOTE: {len(later)} {label} snapshot(s) are dated after the {cutoff.date()} data "
            f"cutoff (latest {later.max().date()}); they are compared with cutoff-day supply.")
