"""Daily and annual series from the Bitcoin Report Library's published release."""
from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ReportLibraryRelease:
    """Verified raw bytes from a single Report Library fetch, reusable across pipelines."""

    report_date: pd.Timestamp
    manifest: dict[str, Any]
    hashes: dict[str, str]
    content: dict[str, bytes]


def fetch_raw_release(
    as_of: pd.Timestamp,
    extra_files: tuple[str, ...] = (),
    *,
    allow_slice: bool = False,
) -> ReportLibraryRelease:
    """Download and SHA-256 verify one Report Library release once for all requested files."""
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
    if report_date > as_of and not allow_slice:
        raise ValueError(f"the Report Library release is for {report_date.date()}; "
                         f"it cannot supply an earlier cutoff ({as_of.date()})")

    content = {}
    for name, expected in hashes.items():
        response = request(f"{REPORT_LIBRARY_URL}/{name}")
        # Pages can briefly serve a new manifest beside the previous data file.
        if hashlib.sha256(response.content).hexdigest() != expected:
            raise ReleaseNotReady(f"{name} does not yet match its release manifest")
        content[name] = response.content
    return ReportLibraryRelease(
        report_date=report_date,
        manifest=manifest,
        hashes=hashes,
        content=content,
    )


def _slice_extra_table(frame: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    if "date" in frame.columns:
        dates = pd.to_datetime(frame["date"], errors="coerce")
        return frame.loc[dates <= as_of].copy()
    if "quarter_end" in frame.columns:
        quarters = pd.to_datetime(frame["quarter_end"], errors="coerce")
        return frame.loc[quarters <= as_of].copy()
    return frame


def fetch_release(
    as_of: pd.Timestamp,
    columns: list[str],
    *,
    allow_slice: bool = False,
    release: ReportLibraryRelease | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """`columns` of the master file through `as_of`, indexed by date, and the annual
    reference file, both from one release and checked against its manifest."""
    daily, annual, _, provenance = fetch_release_files(
        as_of, columns, allow_slice=allow_slice, release=release,
    )
    return daily, annual, provenance


def fetch_release_files(
    as_of: pd.Timestamp,
    columns: list[str],
    extra_files: tuple[str, ...] = (),
    *,
    allow_slice: bool = False,
    release: ReportLibraryRelease | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame], dict[str, Any]]:
    """As fetch_release, plus `extra_files` of the same release as data frames by name."""
    names = (MASTER_FILE, ANNUAL_FILE, *extra_files)
    if release is None:
        release = fetch_raw_release(as_of, extra_files, allow_slice=allow_slice)
    else:
        missing = [name for name in names if name not in release.content]
        if missing:
            raise ValueError(f"Provided Report Library release is missing files: {missing}")
        if release.report_date < as_of:
            raise ReleaseNotReady(f"the Report Library has published through {release.report_date.date()}, "
                                  f"not yet {as_of.date()}")
        if release.report_date > as_of and not allow_slice:
            raise ValueError(f"the Report Library release is for {release.report_date.date()}; "
                             f"it cannot supply an earlier cutoff ({as_of.date()})")

    sliced = release.report_date > as_of
    try:
        daily = pd.read_csv(BytesIO(release.content[MASTER_FILE]), compression="gzip",
                            usecols=["date", *columns], parse_dates=["date"]).set_index("date")
        annual = pd.read_csv(BytesIO(release.content[ANNUAL_FILE]))
        extra = {name: pd.read_csv(BytesIO(release.content[name])) for name in extra_files}
    except ValueError as error:
        raise SourceSchemaError(f"the Report Library release lacks a requested column: {error}") from error
    if not {"series", "year", "value"}.issubset(annual.columns):
        raise SourceSchemaError(f"{ANNUAL_FILE} has an unexpected schema")
    if sliced:
        daily = daily.loc[:as_of]
        annual = annual.loc[pd.to_numeric(annual["year"], errors="coerce") < as_of.year].copy()
        extra = {name: _slice_extra_table(table, as_of) for name, table in extra.items()}
    if daily.empty or daily.index[-1] != as_of:
        raise ValueError(f"{MASTER_FILE} does not run through {as_of.date()}")
    hashes = {name: release.hashes[name] for name in names}
    provenance: dict[str, Any] = {
        "url": REPORT_LIBRARY_URL,
        "release_id": release.manifest.get("release_id"),
        "generated_at": release.manifest.get("generated_at"),
        "sha256": hashes,
    }
    if sliced:
        provenance["sliced_from_report_date"] = release.report_date.date().isoformat()
    return daily, annual, extra, provenance


def annual_series(annual: pd.DataFrame, series: str) -> pd.Series:
    """One series of the annual reference file, indexed by year."""
    rows = annual[annual["series"] == series]
    if rows.empty:
        raise SourceSchemaError(f"{ANNUAL_FILE} has no {series} series")
    return rows.set_index("year")["value"].rename(series).sort_index()


def fetch_savings_inputs(
    as_of: pd.Timestamp,
    *,
    allow_slice: bool = False,
    release: ReportLibraryRelease | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Bitcoin's daily close from the first traded day, and annual U.S. median income."""
    daily, annual, provenance = fetch_release(
        as_of, ["price_close"], allow_slice=allow_slice, release=release,
    )
    price = daily["price_close"].rename("price")
    first_trade = price.first_valid_index()
    if first_trade is None:
        raise ValueError(f"{MASTER_FILE} has no traded price")
    income = annual_series(annual, MEDIAN_INCOME_SERIES)
    income = pd.DataFrame({"Year": income.index.astype(int), "median_household_income_usd": income.to_numpy()})
    return price.loc[first_trade:].to_frame(), income, provenance
