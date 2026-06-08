"""Elasticsearch index definitions for market events."""

from __future__ import annotations

from app.clients.es_client import ElasticsearchClient

# ---------------------------------------------------------------------------
# Index mappings
# ---------------------------------------------------------------------------

KEYWORD_FIELD: dict = {"type": "keyword"}
TEXT_FIELD: dict = {"type": "text"}
DATE_FIELD: dict = {"type": "date"}
BOOL_FIELD: dict = {"type": "boolean"}
INT_FIELD: dict = {"type": "integer"}
FLOAT_FIELD: dict = {"type": "float"}
LONG_FIELD: dict = {"type": "long"}

TEXT_KEYWORD: dict = {"type": "text", "fields": {"raw": {"type": "keyword"}}}

MARKET_EVENT_SOURCES_MAPPING: dict = {
    "mappings": {
        "properties": {
            "source_code": KEYWORD_FIELD,
            "source_name": TEXT_KEYWORD,
            "description": TEXT_FIELD,
            "enabled": BOOL_FIELD,
            "priority": INT_FIELD,
            "base_url": {"type": "keyword", "index": False},
            "apply_url": {"type": "keyword", "index": False},
            "doc_url": {"type": "keyword", "index": False},
            "health_check_url": {"type": "keyword", "index": False},
            "requires_api_key": BOOL_FIELD,
            "credential_key_name": KEYWORD_FIELD,
            "last_check_at": DATE_FIELD,
            "last_check_status": KEYWORD_FIELD,
            "last_error": TEXT_FIELD,
            "created_at": DATE_FIELD,
            "updated_at": DATE_FIELD,
        }
    }
}

MARKET_EVENT_DEFINITIONS_MAPPING: dict = {
    "mappings": {
        "properties": {
            "event_code": KEYWORD_FIELD,
            "event_name": TEXT_KEYWORD,
            "category": KEYWORD_FIELD,
            "event_type": KEYWORD_FIELD,
            "default_importance": KEYWORD_FIELD,
            "country": KEYWORD_FIELD,
            "region": KEYWORD_FIELD,
            "market": KEYWORD_FIELD,
            "currency": KEYWORD_FIELD,
            "source_code": KEYWORD_FIELD,
            "description": TEXT_FIELD,
            "typical_release_rule": TEXT_FIELD,
            "default_watch_window_hours": INT_FIELD,
            "enabled": BOOL_FIELD,
            "created_at": DATE_FIELD,
            "updated_at": DATE_FIELD,
        }
    }
}

MARKET_EVENT_OCCURRENCES_MAPPING: dict = {
    "mappings": {
        "properties": {
            "definition_id": KEYWORD_FIELD,
            "source_code": KEYWORD_FIELD,
            "source_event_id": KEYWORD_FIELD,
            "dedupe_key": KEYWORD_FIELD,
            "title": TEXT_KEYWORD,
            "summary": TEXT_FIELD,
            "category": KEYWORD_FIELD,
            "event_type": KEYWORD_FIELD,
            "status": KEYWORD_FIELD,
            "importance": KEYWORD_FIELD,
            "country": KEYWORD_FIELD,
            "region": KEYWORD_FIELD,
            "market": KEYWORD_FIELD,
            "symbols": KEYWORD_FIELD,
            "asset_classes": KEYWORD_FIELD,
            "scheduled_at": DATE_FIELD,
            "scheduled_timezone": KEYWORD_FIELD,
            "period": KEYWORD_FIELD,
            "is_all_day": BOOL_FIELD,
            "is_confirmed_time": BOOL_FIELD,
            "source_url": {"type": "keyword", "index": False},
            "raw_payload_hash": KEYWORD_FIELD,
            "raw_payload": {"type": "object", "enabled": False},
            "created_at": DATE_FIELD,
            "updated_at": DATE_FIELD,
        }
    }
}

MARKET_EVENT_VALUES_MAPPING: dict = {
    "mappings": {
        "properties": {
            "occurrence_id": KEYWORD_FIELD,
            "value_type": KEYWORD_FIELD,
            "label": TEXT_FIELD,
            "value_text": TEXT_FIELD,
            "value_numeric": FLOAT_FIELD,
            "unit": KEYWORD_FIELD,
            "currency": KEYWORD_FIELD,
            "period": KEYWORD_FIELD,
            "published_at": DATE_FIELD,
            "source_code": KEYWORD_FIELD,
            "raw_payload": {"type": "object", "enabled": False},
            "created_at": DATE_FIELD,
            "updated_at": DATE_FIELD,
        }
    }
}

MARKET_EVENT_IMPACTS_MAPPING: dict = {
    "mappings": {
        "properties": {
            "occurrence_id": KEYWORD_FIELD,
            "symbol": KEYWORD_FIELD,
            "asset_class": KEYWORD_FIELD,
            "market": KEYWORD_FIELD,
            "sector": KEYWORD_FIELD,
            "industry": KEYWORD_FIELD,
            "impact_direction": KEYWORD_FIELD,
            "impact_level": KEYWORD_FIELD,
            "reason": TEXT_FIELD,
            "confidence": FLOAT_FIELD,
            "source": KEYWORD_FIELD,
            "created_at": DATE_FIELD,
            "updated_at": DATE_FIELD,
        }
    }
}

MARKET_EVENT_NEWS_LINKS_MAPPING: dict = {
    "mappings": {
        "properties": {
            "occurrence_id": KEYWORD_FIELD,
            "source_code": KEYWORD_FIELD,
            "news_id": KEYWORD_FIELD,
            "title": TEXT_KEYWORD,
            "url": {"type": "keyword", "index": False},
            "publisher": KEYWORD_FIELD,
            "published_at": DATE_FIELD,
            "summary": TEXT_FIELD,
            "symbols": KEYWORD_FIELD,
            "raw_payload": {"type": "object", "enabled": False},
            "created_at": DATE_FIELD,
            "updated_at": DATE_FIELD,
        }
    }
}

MARKET_EVENT_ANALYSIS_MAPPING: dict = {
    "mappings": {
        "properties": {
            "occurrence_id": KEYWORD_FIELD,
            "analysis_type": KEYWORD_FIELD,
            "title": TEXT_FIELD,
            "content": TEXT_FIELD,
            "model_name": KEYWORD_FIELD,
            "provider_name": KEYWORD_FIELD,
            "prompt_version": KEYWORD_FIELD,
            "confidence": FLOAT_FIELD,
            "created_by": KEYWORD_FIELD,
            "created_at": DATE_FIELD,
            "updated_at": DATE_FIELD,
        }
    }
}

MARKET_EVENT_SYNC_RUNS_MAPPING: dict = {
    "mappings": {
        "properties": {
            "source_code": KEYWORD_FIELD,
            "provider_name": KEYWORD_FIELD,
            "sync_type": KEYWORD_FIELD,
            "status": KEYWORD_FIELD,
            "started_at": DATE_FIELD,
            "finished_at": DATE_FIELD,
            "range_start": DATE_FIELD,
            "range_end": DATE_FIELD,
            "total_count": INT_FIELD,
            "created_count": INT_FIELD,
            "updated_count": INT_FIELD,
            "skipped_count": INT_FIELD,
            "failed_count": INT_FIELD,
            "error_message": TEXT_FIELD,
            "error_detail": TEXT_FIELD,
            "metadata": {"type": "object", "enabled": False},
            "created_at": DATE_FIELD,
            "updated_at": DATE_FIELD,
        }
    }
}


# ---------------------------------------------------------------------------
# Index creation helper
# ---------------------------------------------------------------------------

INDEX_MAPPINGS: dict[str, dict] = {
    "market_event_sources": MARKET_EVENT_SOURCES_MAPPING,
    "market_event_definitions": MARKET_EVENT_DEFINITIONS_MAPPING,
    "market_event_occurrences": MARKET_EVENT_OCCURRENCES_MAPPING,
    "market_event_values": MARKET_EVENT_VALUES_MAPPING,
    "market_event_impacts": MARKET_EVENT_IMPACTS_MAPPING,
    "market_event_news_links": MARKET_EVENT_NEWS_LINKS_MAPPING,
    "market_event_analysis": MARKET_EVENT_ANALYSIS_MAPPING,
    "market_event_sync_runs": MARKET_EVENT_SYNC_RUNS_MAPPING,
}


def ensure_market_event_indices(
    es_client: ElasticsearchClient,
    index_prefix: str = "market_event_",
    suffix: str = "_v1",
) -> None:
    """Create all market event ES indices if they don't already exist."""
    for name, mapping in INDEX_MAPPINGS.items():
        full_name = f"{index_prefix}{name.replace('market_event_', '')}{suffix}"
        es_client.create_index_if_missing(full_name, mapping)
