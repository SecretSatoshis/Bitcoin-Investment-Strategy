"""U.S. median household income from FRED."""
from __future__ import annotations

from io import StringIO
from typing import Any

import pandas as pd

from ..config import FRED_MEDIAN_INCOME_URL
from ..io import SourceSchemaError, request
from ..validation import validate_income


def fetch_fred_median_income() -> tuple[pd.DataFrame, dict[str, Any]]:
    # FRED sometimes accepts a connection and then stalls. A short timeout lets the
    # release fall back to its verified saved copy instead of hanging the daily run.
    response = request(FRED_MEDIAN_INCOME_URL, timeout=20, attempts=2)
    # An empty or HTML maintenance page fails to parse here; that is a passing outage,
    # not a schema change, so it raises an ordinary error.
    frame = pd.read_csv(StringIO(response.text))
    if not {"observation_date", "MEHOINUSA646N"}.issubset(frame.columns):
        raise SourceSchemaError("FRED median-income response has an unexpected schema")
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame["median_household_income_usd"] = pd.to_numeric(
        frame["MEHOINUSA646N"], errors="coerce"
    )
    if frame["observation_date"].isna().any():
        raise SourceSchemaError("FRED income contains invalid observation dates")
    frame = pd.DataFrame(
        {
            "Year": frame["observation_date"].dt.year.astype(int),
            "median_household_income_usd": frame["median_household_income_usd"],
        }
    )
    try:
        validate_income(frame)
    except ValueError as error:
        raise SourceSchemaError(f"FRED median-income values are unusable: {error}") from error
    return frame.sort_values("Year"), {
        "url": response.url,
        "series": "MEHOINUSA646N",
        "units": "current USD",
    }
