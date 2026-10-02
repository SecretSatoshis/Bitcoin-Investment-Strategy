"""Daily and annual series from the Bitcoin Report Library's published release."""
from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any

import pandas as pd

from ..config import REPORT_LIBRARY_URL
from ..io import SourceSchemaError, request

MASTER_FILE = "master_metrics_data.csv.gz"
ANNUAL_FILE = "annual_reference_data.csv"
MEDIAN_INCOME_SERIES = "us_median_household_income_usd"


class ReleaseNotReady(RuntimeError):
    """The Report Library has not yet published the requested day."""


def fetch_release(as_of: pd.Timestamp, columns: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """`columns` of the master file through `as_of`, indexed by date, and the annual
    reference file, both from one release and checked against its manifest."""
    daily, annual, _, provenance = fetch_release_files(as_of, columns)
    return daily, annual, provenance


def fetch_release_files(as_of: pd.Timestamp, columns: list[str], extra_files: tuple[str, ...] = ()
                        ) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame], dict[str, Any]]:
    """As fetch_release, plus `extra_files` of the same release as data frames by name."""
    manifest = request(f"{REPORT_LIBRARY_URL}/release_manifest.json").json()
    names = (MASTER_FILE, ANNUAL_FILE, *extra_files)
    try:
        report_date = pd.Timestamp(manifest["report_date"])
        hashes = {name: manifest["files"][name]["sha256"] for name in names}
    except (KeyError, TypeError, ValueError) as error:
        raise SourceSchemaError("Report Library manifest has an unexpected schema") from error
    if report_date < as_of:
        raise ReleaseNotReady(f"the Report Library has published through {report_date.date()}, "
                              f"not yet {as_of.date()}")
    if report_date > as_of:
        raise ValueError(f"the Report Library release is for {report_date.date()}; "
                         f"it cannot supply an earlier cutoff ({as_of.date()})")

    content = {}
    for name, expected in hashes.items():
        response = request(f"{REPORT_LIBRARY_URL}/{name}")
        # Pages can briefly serve a new manifest beside the previous data file.
        if hashlib.sha256(response.content).hexdigest() != expected:
            raise ReleaseNotReady(f"{name} does not yet match its release manifest")
        content[name] = response.content
    try:
        daily = pd.read_csv(BytesIO(content[MASTER_FILE]), compression="gzip",
                            usecols=["date", *columns], parse_dates=["date"]).set_index("date")
        annual = pd.read_csv(BytesIO(content[ANNUAL_FILE]))
        extra = {name: pd.read_csv(BytesIO(content[name])) for name in extra_files}
    except ValueError as error:
        raise SourceSchemaError(f"the Report Library release lacks a requested column: {error}") from error
    if not {"series", "year", "value"}.issubset(annual.columns):
        raise SourceSchemaError(f"{ANNUAL_FILE} has an unexpected schema")
    if daily.empty or daily.index[-1] != as_of:
        raise ValueError(f"{MASTER_FILE} does not run through {as_of.date()}")
    return daily, annual, extra, {
        "url": REPORT_LIBRARY_URL,
        "release_id": manifest.get("release_id"),
        "generated_at": manifest.get("generated_at"),
        "sha256": hashes,
    }


def annual_series(annual: pd.DataFrame, series: str) -> pd.Series:
    """One series of the annual reference file, indexed by year."""
    rows = annual[annual["series"] == series]
    if rows.empty:
        raise SourceSchemaError(f"{ANNUAL_FILE} has no {series} series")
    return rows.set_index("year")["value"].rename(series).sort_index()


def fetch_savings_inputs(as_of: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Bitcoin's daily close from the first traded day, and annual U.S. median income."""
    daily, annual, provenance = fetch_release(as_of, ["price_close"])
    price = daily["price_close"].rename("price")
    first_trade = price.first_valid_index()
    if first_trade is None:
        raise ValueError(f"{MASTER_FILE} has no traded price")
    income = annual_series(annual, MEDIAN_INCOME_SERIES)
    income = pd.DataFrame({"Year": income.index.astype(int), "median_household_income_usd": income.to_numpy()})
    return price.loc[first_trade:].to_frame(), income, provenance
