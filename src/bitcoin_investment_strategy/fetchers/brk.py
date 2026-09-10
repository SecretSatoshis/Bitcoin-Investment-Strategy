from __future__ import annotations

from typing import Any

import pandas as pd

from ..config import BRK_BASE_URL, BRK_SERIES, START_DATE
from ..io import request


def fetch_brk_daily(as_of: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, Any]]:
    end_exclusive = (as_of + pd.Timedelta(days=1)).date().isoformat()
    expected = pd.date_range(START_DATE, end_exclusive, freq="D", inclusive="left", name="date")
    # BRK day1 uses zero-based days since 2009-01-01 and an exclusive end.
    epoch = pd.Timestamp("2009-01-01")
    expected_start = (pd.Timestamp(START_DATE) - epoch).days
    expected_end = (pd.Timestamp(end_exclusive) - epoch).days
    frames: dict[str, pd.Series] = {}
    provenance: dict[str, Any] = {}

    for position, source_name in enumerate(BRK_SERIES, start=1):
        print(f"  BRK [{position:>2}/{len(BRK_SERIES)}] {source_name}")
        response = request(
            f"{BRK_BASE_URL}/series/{source_name}/day",
            params={"format": "json", "start": START_DATE, "end": end_exclusive},
        )
        payload = response.json()
        values = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(values, list) or len(values) != len(expected):
            raise ValueError(
                f"{source_name}: expected {len(expected)} daily observations, "
                f"received {len(values) if isinstance(values, list) else 'invalid payload'}"
            )
        if (
            payload.get("index") != "day1"
            or type(payload.get("start")) is not int
            or type(payload.get("end")) is not int
            or payload["start"] != expected_start
            or payload["end"] != expected_end
        ):
            raise ValueError(
                f"{source_name}: expected BRK day1 range [{expected_start}, {expected_end}), "
                f"received index={payload.get('index')!r}, "
                f"start={payload.get('start')!r}, end={payload.get('end')!r}"
            )
        series = pd.Series(pd.to_numeric(values, errors="raise"), index=expected, name=source_name)
        frames[source_name] = series
        provenance[source_name] = {
            "url": response.url,
            "response_index": payload.get("index"),
            "response_start": payload.get("start"),
            "response_end": payload.get("end"),
            "version": payload.get("version"),
            "stamp": payload.get("stamp"),
            "observations": len(series),
        }

    frame = pd.concat(frames.values(), axis=1)
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("BRK daily index is not unique and ordered")
    return frame, provenance
