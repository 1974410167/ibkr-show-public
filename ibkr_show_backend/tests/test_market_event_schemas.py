"""Tests for market event schemas, enums, and utility functions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas.market_event import (
    MarketEventCategory,
    MarketEventImportance,
    MarketEventListItem,
    MarketEventOccurrence,
    MarketEventSource,
    MarketEventSourceCode,
    MarketEventStatus,
    MarketEventType,
    MarketEventUpsertInput,
    MarketEventValueInput,
    MarketEventValueType,
)
from app.utils.market_event import (
    calculate_event_risk_level,
    generate_dedupe_key,
    stable_json_hash,
)


# ---------------------------------------------------------------------------
# Enum / Literal import tests
# ---------------------------------------------------------------------------


def test_source_code_literal():
    """MarketEventSourceCode accepts valid values."""
    valid: MarketEventSourceCode = "BLS"
    assert valid == "BLS"


def test_category_literal():
    valid: MarketEventCategory = "MACRO"
    assert valid == "MACRO"


def test_event_type_literal():
    valid: MarketEventType = "CPI"
    assert valid == "CPI"


def test_status_literal():
    valid: MarketEventStatus = "SCHEDULED"
    assert valid == "SCHEDULED"


def test_importance_literal():
    valid: MarketEventImportance = "CRITICAL"
    assert valid == "CRITICAL"


def test_value_type_literal():
    valid: MarketEventValueType = "ACTUAL"
    assert valid == "ACTUAL"


# ---------------------------------------------------------------------------
# dedupe_key tests
# ---------------------------------------------------------------------------


def test_dedupe_key_deterministic():
    """Same inputs produce the same key."""
    dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    k1 = generate_dedupe_key("BLS", "CPI", dt, "CPI Release", "US", "2026-06", ["SPY"])
    k2 = generate_dedupe_key("BLS", "CPI", dt, "CPI Release", "US", "2026-06", ["SPY"])
    assert k1 == k2


def test_dedupe_key_different_inputs():
    """Different inputs produce different keys."""
    dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    k1 = generate_dedupe_key("BLS", "CPI", dt, "CPI Release")
    k2 = generate_dedupe_key("BLS", "PPI", dt, "PPI Release")
    assert k1 != k2


def test_dedupe_key_symbols_order():
    """Symbol order doesn't affect the key (sorted internally)."""
    dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    k1 = generate_dedupe_key("BLS", "CPI", dt, "Test", symbols=["B", "A"])
    k2 = generate_dedupe_key("BLS", "CPI", dt, "Test", symbols=["A", "B"])
    assert k1 == k2


def test_dedupe_key_optional_fields():
    """None optional fields don't break key generation."""
    dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    k = generate_dedupe_key("BLS", "CPI", dt, "Test")
    assert isinstance(k, str) and len(k) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# raw_payload_hash tests
# ---------------------------------------------------------------------------


def test_stable_json_hash_key_order():
    """Hash is the same regardless of dict key insertion order."""
    payload1 = {"b": 2, "a": 1}
    payload2 = {"a": 1, "b": 2}
    assert stable_json_hash(payload1) == stable_json_hash(payload2)


def test_stable_json_hash_none():
    assert stable_json_hash(None) == ""


def test_stable_json_hash_deterministic():
    payload = {"cpi": 3.4, "month": "2026-06"}
    h1 = stable_json_hash(payload)
    h2 = stable_json_hash(payload)
    assert h1 == h2


# ---------------------------------------------------------------------------
# Schema serialization tests
# ---------------------------------------------------------------------------


def test_occurrence_schema_serialization():
    """MarketEventOccurrence can serialize list and dict fields."""
    dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    occ = MarketEventOccurrence(
        source_code="BLS",
        dedupe_key="abc123",
        title="CPI Release",
        category="MACRO",
        event_type="CPI",
        scheduled_at=dt,
        symbols=["AMD.US", "ORCL.US"],
        asset_classes=["equity", "rates"],
        raw_payload={"key": "value"},
    )
    data = occ.model_dump()
    assert data["symbols"] == ["AMD.US", "ORCL.US"]
    assert data["asset_classes"] == ["equity", "rates"]
    assert data["raw_payload"] == {"key": "value"}


def test_source_schema_defaults():
    src = MarketEventSource(
        source_code="BLS",
        source_name="Bureau of Labor Statistics",
    )
    assert src.enabled is True
    assert src.priority == 100
    assert src.requires_api_key is False


def test_upsert_input_schema():
    dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    inp = MarketEventUpsertInput(
        source_code="BLS",
        title="CPI",
        category="MACRO",
        event_type="CPI",
        scheduled_at=dt,
    )
    assert inp.status == "SCHEDULED"
    assert inp.importance == "MEDIUM"
    assert inp.symbols == []


def test_list_item_schema():
    dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    item = MarketEventListItem(
        id="test-id",
        title="CPI Release",
        category="MACRO",
        event_type="CPI",
        status="SCHEDULED",
        importance="HIGH",
        source_code="BLS",
        scheduled_at=dt,
    )
    assert item.has_actual_value is False
    assert item.values == []
    assert item.impacts == []


# ---------------------------------------------------------------------------
# Risk calculation tests
# ---------------------------------------------------------------------------


def test_risk_level_critical():
    events = [{"importance": "CRITICAL"}, {"importance": "LOW"}]
    level, c, h, m, l = calculate_event_risk_level(events)
    assert level == "CRITICAL"
    assert c == 1


def test_risk_level_high_two_highs():
    events = [{"importance": "HIGH"}, {"importance": "HIGH"}]
    level, c, h, m, l = calculate_event_risk_level(events)
    assert level == "HIGH"
    assert h == 2


def test_risk_level_high_one_high_three_medium():
    events = [
        {"importance": "HIGH"},
        {"importance": "MEDIUM"},
        {"importance": "MEDIUM"},
        {"importance": "MEDIUM"},
    ]
    level, c, h, m, l = calculate_event_risk_level(events)
    assert level == "HIGH"


def test_risk_level_medium_three_mediums():
    events = [
        {"importance": "MEDIUM"},
        {"importance": "MEDIUM"},
        {"importance": "MEDIUM"},
    ]
    level, c, h, m, l = calculate_event_risk_level(events)
    assert level == "MEDIUM"


def test_risk_level_medium_one_high():
    events = [{"importance": "HIGH"}]
    level, c, h, m, l = calculate_event_risk_level(events)
    assert level == "MEDIUM"


def test_risk_level_low():
    events = [{"importance": "LOW"}, {"importance": "LOW"}]
    level, c, h, m, l = calculate_event_risk_level(events)
    assert level == "LOW"


def test_risk_level_empty():
    events: list[dict] = []
    level, c, h, m, l = calculate_event_risk_level(events)
    assert level == "LOW"
    assert c == 0 and h == 0 and m == 0 and l == 0
