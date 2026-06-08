"""Market event utility functions -- dedupe_key, raw_payload_hash, risk calculation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def stable_json_hash(payload: dict[str, Any] | None) -> str:
    """Hash a JSON-serializable dict with sorted keys for deterministic output."""
    if payload is None:
        return ""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_dedupe_key(
    source_code: str,
    event_type: str,
    scheduled_at: datetime,
    title: str,
    market: str | None = None,
    period: str | None = None,
    symbols: list[str] | None = None,
) -> str:
    """Generate a deterministic deduplication key for an event occurrence.

    Same inputs always produce the same key.  Does NOT include any API keys
    or private data.
    """
    parts = [
        source_code,
        event_type,
        scheduled_at.isoformat(),
        title,
        market or "",
        period or "",
        ",".join(sorted(symbols)) if symbols else "",
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def calculate_event_risk_level(
    events: list[dict[str, Any]],
) -> tuple[str, int, int, int, int]:
    """Calculate risk level from a list of events.

    Returns (risk_level, critical_count, high_count, medium_count, low_count).
    """
    critical = sum(1 for e in events if e.get("importance") == "CRITICAL")
    high = sum(1 for e in events if e.get("importance") == "HIGH")
    medium = sum(1 for e in events if e.get("importance") == "MEDIUM")
    low = sum(1 for e in events if e.get("importance") == "LOW")

    if critical >= 1:
        level = "CRITICAL"
    elif high >= 2 or (high >= 1 and medium >= 3):
        level = "HIGH"
    elif medium >= 3 or high >= 1:
        level = "MEDIUM"
    else:
        level = "LOW"

    return level, critical, high, medium, low


def utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)
