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


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


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
            if attempt == attempts:
                break
            retry_after = getattr(error.response, "headers", {}).get("Retry-After") if error.response else None
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
