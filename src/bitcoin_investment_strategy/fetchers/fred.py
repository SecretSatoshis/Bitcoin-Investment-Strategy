from __future__ import annotations

from io import StringIO
from typing import Any

import pandas as pd

from ..config import FRED_MEDIAN_INCOME_URL
from ..io import request


def fetch_fred_median_income() -> tuple[pd.DataFrame, dict[str, Any]]:
    # FRED occasionally accepts a connection but delays the response body. The
    # central pipeline has a committed verified fallback, so do not stall an
    # entire daily run for several minutes on this slow annual source.
    response = request(FRED_MEDIAN_INCOME_URL, timeout=20, attempts=2)
    frame = pd.read_csv(StringIO(response.text))
    date_column = next((column for column in ("DATE", "observation_date") if column in frame.columns), None)
    if date_column is None or "MEHOINUSA646N" not in frame.columns:
        raise ValueError("FRED median-income response has an unexpected schema")
    frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce")
    frame["median_household_income_usd"] = pd.to_numeric(
        frame["MEHOINUSA646N"], errors="coerce"
    )
    frame = frame.dropna(subset=[date_column, "median_household_income_usd"])
    frame = pd.DataFrame(
        {
            "Year": frame[date_column].dt.year.astype(int),
            "median_household_income_usd": frame["median_household_income_usd"],
        }
    ).drop_duplicates("Year", keep="last")
    return frame.sort_values("Year"), {
        "url": response.url,
        "series": "MEHOINUSA646N",
        "units": "current USD",
    }
