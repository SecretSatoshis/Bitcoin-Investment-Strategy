"""HTTP requests, checksums, atomic writes and release metadata."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import requests
import pandas as pd


USER_AGENT = "bitcoin-investment-strategy-data/0.1 (+public research notebook)"

# Statuses worth retrying: timeouts, rate limits and server-side failures. Anything else
# (404 for a renamed series, 400 for a bad request) will not change on a retry.
TRANSIENT_STATUSES = {408, 425, 429}


class SourceSchemaError(ValueError):
    """An upstream response has a shape the fetcher does not understand.

    Unlike a timeout, this persists until the fetcher is updated, so a saved copy of the
    data must not stand in for it.
    """


def sha256(path: Path | str) -> str:
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_artifacts(manifest: dict[str, Any], root: Path, paths) -> None:
    """Require each file's checksum to match its entry in a release manifest."""
    for path in paths:
        relative = str(Path(path).resolve().relative_to(Path(root).resolve()))
        if sha256(path) != manifest["artifacts"][relative]["sha256"]:
            raise ValueError(f"{relative}: checksum does not match the release manifest")


def artifact_metadata(path: Path) -> dict[str, Any]:
    """Checksum, size and, for a CSV, its row count and date or year coverage."""
    metadata: dict[str, Any] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    if path.suffix == ".csv":
        frame = pd.read_csv(path)
        metadata.update({"rows": len(frame), "columns": len(frame.columns)})
        if "date" in frame.columns and len(frame):
            dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
            if len(dates):
                metadata.update({"data_start": dates.min().date().isoformat(), "data_end": dates.max().date().isoformat()})
        elif "Year" in frame.columns and len(frame):
            years = pd.to_numeric(frame["Year"], errors="coerce").dropna()
            if len(years):
                metadata.update({"data_start": str(int(years.min())), "data_end": str(int(years.max()))})
    return metadata


def release_id(data_end: pd.Timestamp, artifacts: dict[str, dict[str, Any]]) -> str:
    """The data end date plus a short fingerprint of every artifact's checksum."""
    fingerprint = hashlib.sha256(
        "".join(metadata["sha256"] for _, metadata in sorted(artifacts.items())).encode()
    ).hexdigest()[:12]
    return f"{data_end.date().isoformat()}-{fingerprint}"


def request(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
    attempts: int = 4,
) -> requests.Response:
    merged_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, params=params, headers=merged_headers, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            # A failed Response is falsy (its truthiness is `.ok`), so test identity.
            response = error.response
            status = response.status_code if response is not None else None
            if status is not None and status not in TRANSIENT_STATUSES and status < 500:
                raise RuntimeError(f"request failed with HTTP {status}: {url}") from error
            if attempt == attempts:
                break
            retry_after = response.headers.get("Retry-After") if response is not None else None
            wait = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
            time.sleep(min(wait, 30))
    raise RuntimeError(f"request failed after {attempts} attempts: {url}") from last_error


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def atomic_write_csv(path: Path, frame: pd.DataFrame, *, index: bool = False) -> None:
    atomic_write_text(path, frame.to_csv(index=index, lineterminator="\n"))
