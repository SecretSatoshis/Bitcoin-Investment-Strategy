"""Public company and government bitcoin treasuries from CoinGecko, read when the demand
notebook runs.

CoinGecko's API terms allow showing its data with "Powered by CoinGecko" but not
redistributing it, and allow a local copy only if it is refreshed at least every 24 hours.
So nothing from it is committed: the snapshots live in a git-ignored cache and are fetched
again once they are a day old.
"""
from __future__ import annotations

import json
import os
from typing import Any

import numpy as np
import pandas as pd

from ..config import ROOT
from ..io import SourceSchemaError, atomic_write_csv, atomic_write_json, request
from .config import COINGECKO_BASE_URL, REFERENCE_DIR
from .transforms import build_company_treasuries, build_government_treasuries
from .validation import validate_treasuries

CACHE_DIR = ROOT / ".cache" / "coingecko"
MAX_AGE = pd.Timedelta(hours=24)

PAGE_SIZE = 250


def fetch_public_treasuries(entity_type: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    if entity_type not in {"companies", "governments"}:
        raise ValueError(f"unsupported treasury entity type: {entity_type}")
    # An optional free Demo key raises the rate limit; the keyless API works without one.
    key = os.environ.get("COINGECKO_API_KEY")
    headers = {"x-cg-demo-api-key": key} if key else {}
    records: list[dict[str, Any]] = []
    for page in range(1, 41):
        response = request(
            f"{COINGECKO_BASE_URL}/{entity_type}/public_treasury/bitcoin",
            params={"per_page": PAGE_SIZE, "page": page},
            headers=headers,
        )
        payload = response.json()
        batch = payload.get(entity_type) if isinstance(payload, dict) else None
        if not isinstance(batch, list):
            raise SourceSchemaError(f"CoinGecko {entity_type}: no treasury records")
        records += batch
        if len(batch) < PAGE_SIZE:
            break
    if not records:
        raise SourceSchemaError(f"CoinGecko {entity_type}: no treasury records")
    frame = pd.DataFrame(records)
    aliases = {
        "name": "entity",
        "symbol": "ticker",
        "total_holdings": "btc",
        "total_entry_value_usd": "cost_basis_usd",
        "total_current_value_usd": "current_value_usd",
        "percentage_of_total_supply": "pct_of_supply",
    }
    frame = frame.rename(columns=aliases)
    if not {"entity", "btc"}.issubset(frame.columns):
        raise SourceSchemaError(f"CoinGecko {entity_type}: missing entity or holdings fields")
    for column in ("btc", "cost_basis_usd", "current_value_usd", "pct_of_supply"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["entity", "btc"]).sort_values("btc", ascending=False)
    frame = frame.drop_duplicates("entity", keep="first").reset_index(drop=True)
    # The response states its own total, so a missing page cannot pass unnoticed.
    reported = payload.get("total_holdings")
    if reported is not None and not np.isclose(frame["btc"].sum(), float(reported), rtol=1e-6):
        raise ValueError(f"CoinGecko {entity_type}: rows sum to {frame['btc'].sum():,.2f} BTC, "
                         f"not the reported {float(reported):,.2f}")
    provenance = {
        "url": response.url,
        "authenticated": bool(key),
        "entity_type": entity_type,
        "total_holdings_reported": reported,
        "observations": len(frame),
    }
    return frame, provenance


def _snapshot(entity_type: str, cache_dir) -> tuple[pd.DataFrame, pd.Timestamp]:
    """A snapshot no more than a day old: the cached copy, or a fresh fetch that replaces it."""
    data, meta = cache_dir / f"{entity_type}.csv", cache_dir / f"{entity_type}.json"
    now = pd.Timestamp.now(tz="UTC")
    if data.exists() and meta.exists():
        retrieved = pd.Timestamp(json.loads(meta.read_text())["retrieved_at_utc"])
        if now - retrieved <= MAX_AGE:
            return pd.read_csv(data), retrieved
    frame, _ = fetch_public_treasuries(entity_type)
    atomic_write_csv(data, frame, index=False)
    atomic_write_json(meta, {"retrieved_at_utc": now.isoformat()})
    return frame, now


def load_treasuries(cache_dir=CACHE_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Company and government treasuries, each stamped with the day CoinGecko was read; the
    government table carries Secret Satoshis' acquisition classification."""
    companies, company_time = _snapshot("companies", cache_dir)
    governments, government_time = _snapshot("governments", cache_dir)
    companies = build_company_treasuries(companies, company_time.tz_localize(None).normalize())
    classifications = pd.read_csv(REFERENCE_DIR / "government_acquisition_types.csv")
    governments = build_government_treasuries(governments, classifications,
                                              government_time.tz_localize(None).normalize())
    validate_treasuries(companies, "company treasuries")
    validate_treasuries(governments, "government treasuries")
    return companies, governments
