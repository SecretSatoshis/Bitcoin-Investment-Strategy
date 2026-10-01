"""Bitcoin's daily close from the Bitcoin Report Library's published release."""
from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any

import pandas as pd

from ..config import REPORT_LIBRARY_URL
from ..io import SourceSchemaError, request

MASTER_FILE = "master_metrics_data.csv.gz"


class ReleaseNotReady(RuntimeError):
    """The Report Library has not yet published the requested day."""


def fetch_bitcoin_price(as_of: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, Any]]:
    """The daily close from the first traded day through `as_of`, checked against the
    release manifest's checksum."""
    manifest = request(f"{REPORT_LIBRARY_URL}/release_manifest.json").json()
    try:
        report_date = pd.Timestamp(manifest["report_date"])
        expected_sha = manifest["files"][MASTER_FILE]["sha256"]
    except (KeyError, TypeError, ValueError) as error:
        raise SourceSchemaError("Report Library manifest has an unexpected schema") from error
    if report_date < as_of:
        raise ReleaseNotReady(f"the Report Library has published through {report_date.date()}, "
                              f"not yet {as_of.date()}")
    if report_date > as_of:
        raise ValueError(f"the Report Library release is for {report_date.date()}; "
                         f"it cannot supply an earlier cutoff ({as_of.date()})")

    response = request(f"{REPORT_LIBRARY_URL}/{MASTER_FILE}")
    # Pages can briefly serve a new manifest beside the previous data file.
    if hashlib.sha256(response.content).hexdigest() != expected_sha:
        raise ReleaseNotReady(f"{MASTER_FILE} does not yet match its release manifest")
    try:
        frame = pd.read_csv(BytesIO(response.content), compression="gzip",
                            usecols=["date", "price_close"], parse_dates=["date"])
    except ValueError as error:
        raise SourceSchemaError(f"{MASTER_FILE} has no date or price_close column") from error

    price = frame.set_index("date")["price_close"].rename("price")
    first_trade = price.first_valid_index()
    if first_trade is None or price.index[-1] != as_of:
        raise ValueError(f"{MASTER_FILE} does not run through {as_of.date()}")
    return price.loc[first_trade:].to_frame(), {
        "url": response.url,
        "release_id": manifest.get("release_id"),
        "generated_at": manifest.get("generated_at"),
        "sha256": expected_sha,
    }
