"""Market Event ES repository -- CRUD for all market event indices."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.clients.es_client import ElasticsearchClient
from app.core.config import Settings
from app.schemas.market_event import (
    MarketEventAnalysis,
    MarketEventImpact,
    MarketEventImpactInput,
    MarketEventListItem,
    MarketEventNewsLink,
    MarketEventNewsLinkInput,
    MarketEventOccurrence,
    MarketEventSource,
    MarketEventSyncRun,
    MarketEventUpsertInput,
    MarketEventValue,
    MarketEventValueInput,
    UpsertResult,
)
from app.services.market_event_seed import get_seed_sources
from app.utils.market_event import (
    generate_dedupe_key,
    stable_json_hash,
    utc_now,
)

logger = logging.getLogger(__name__)


def _source_priority_sort_key(doc: dict) -> tuple[int, str]:
    try:
        priority = int(doc.get("priority") or 100)
    except (TypeError, ValueError):
        priority = 100
    return priority, str(doc.get("source_code") or "")


class MarketEventRepository:
    """ES CRUD for market event documents."""

    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self._es = es_client
        self._s = settings

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def get_source(self, source_code: str) -> dict | None:
        resp = self._es.search(
            self._s.es_market_event_source_index,
            {"query": {"term": {"source_code": source_code}}, "size": 1},
        )
        hits = resp.get("hits", {}).get("hits", [])
        if not hits:
            return None
        doc = dict(hits[0]["_source"])
        doc["_id"] = hits[0]["_id"]
        return doc

    def list_sources(self) -> list[dict]:
        resp = self._es.search(
            self._s.es_market_event_source_index,
            {"query": {"match_all": {}}, "size": 100},
        )
        results = []
        for hit in resp.get("hits", {}).get("hits", []):
            doc = dict(hit["_source"])
            doc["_id"] = hit["_id"]
            results.append(doc)
        return sorted(results, key=_source_priority_sort_key)

    def upsert_source(self, doc: dict) -> str:
        code = doc["source_code"]
        now = utc_now().isoformat()
        doc.setdefault("created_at", now)
        doc["updated_at"] = now
        return self._es.index_document(
            self._s.es_market_event_source_index, id=code, document=doc
        )["_id"]

    def update_source(self, source_code: str, updates: dict) -> None:
        existing = self.get_source(source_code)
        if not existing:
            return
        existing.pop("_id", None)
        existing.update(updates)
        existing["updated_at"] = utc_now().isoformat()
        self._es.index_document(
            self._s.es_market_event_source_index, id=source_code, document=existing
        )

    def seed_sources(self) -> int:
        """Insert default sources if they don't exist. Returns count inserted."""
        count = 0
        for doc in get_seed_sources():
            if not self.get_source(doc["source_code"]):
                self.upsert_source(doc)
                count += 1
        return count

    # ------------------------------------------------------------------
    # Occurrences
    # ------------------------------------------------------------------

    def get_occurrence(self, occurrence_id: str) -> dict | None:
        resp = self._es.get(self._s.es_market_event_occurrence_index, occurrence_id)
        if not resp:
            return None
        doc = dict(resp["_source"])
        doc["_id"] = resp["_id"]
        return doc

    def get_occurrence_by_dedupe_key(self, dedupe_key: str) -> dict | None:
        resp = self._es.search(
            self._s.es_market_event_occurrence_index,
            {"query": {"term": {"dedupe_key": dedupe_key}}, "size": 1},
        )
        hits = resp.get("hits", {}).get("hits", [])
        if not hits:
            return None
        doc = dict(hits[0]["_source"])
        doc["_id"] = hits[0]["_id"]
        return doc

    def upsert_occurrence(self, input_data: MarketEventUpsertInput) -> UpsertResult:
        """Upsert a single occurrence using dedupe_key for idempotency."""
        dedupe_key = generate_dedupe_key(
            source_code=input_data.source_code,
            event_type=input_data.event_type,
            scheduled_at=input_data.scheduled_at,
            title=input_data.title,
            market=input_data.market,
            period=input_data.period,
            symbols=input_data.symbols,
        )
        raw_hash = stable_json_hash(input_data.raw_payload)
        now = utc_now()

        existing = self.get_occurrence_by_dedupe_key(dedupe_key)

        doc = input_data.model_dump()
        doc["dedupe_key"] = dedupe_key
        doc["raw_payload_hash"] = raw_hash

        if existing:
            # Update if raw_payload_hash changed or status changed
            old_hash = existing.get("raw_payload_hash")
            old_status = existing.get("status")
            if old_hash == raw_hash and old_status == input_data.status:
                return UpsertResult(skipped_count=1, occurrence_ids=[existing["_id"]])
            doc["created_at"] = existing.get("created_at", now.isoformat())
            doc["updated_at"] = now.isoformat()
            doc_id = existing["_id"]
        else:
            doc["created_at"] = now.isoformat()
            doc["updated_at"] = now.isoformat()
            doc_id = dedupe_key  # Use dedupe_key as ES doc ID

        self._es.index_document(
            self._s.es_market_event_occurrence_index, id=doc_id, document=doc
        )

        if existing:
            return UpsertResult(updated_count=1, occurrence_ids=[doc_id])
        return UpsertResult(created_count=1, occurrence_ids=[doc_id])

    def upsert_occurrences(self, inputs: list[MarketEventUpsertInput]) -> UpsertResult:
        """Upsert multiple occurrences."""
        result = UpsertResult()
        for inp in inputs:
            try:
                r = self.upsert_occurrence(inp)
                result.created_count += r.created_count
                result.updated_count += r.updated_count
                result.skipped_count += r.skipped_count
                result.failed_count += r.failed_count
                result.occurrence_ids.extend(r.occurrence_ids)
            except Exception as exc:
                result.failed_count += 1
                result.errors.append(str(exc))
                logger.error("Failed to upsert occurrence %s: %s", inp.title, exc)
        return result

    def list_occurrences(
        self,
        query_body: dict,
        size: int = 50,
        from_: int = 0,
        sort: list | None = None,
    ) -> tuple[list[dict], int]:
        """Search occurrences with a pre-built ES query body."""
        body: dict[str, Any] = {
            "query": query_body,
            "size": size,
            "from": from_,
        }
        if sort:
            body["sort"] = sort

        resp = self._es.search(self._s.es_market_event_occurrence_index, body)
        total = resp.get("hits", {}).get("total", {}).get("value", 0)
        items = []
        for hit in resp.get("hits", {}).get("hits", []):
            doc = dict(hit["_source"])
            doc["_id"] = hit["_id"]
            items.append(doc)
        return items, total

    # ------------------------------------------------------------------
    # Values
    # ------------------------------------------------------------------

    def get_values_for_occurrence(self, occurrence_id: str) -> list[dict]:
        resp = self._es.search(
            self._s.es_market_event_value_index,
            {"query": {"term": {"occurrence_id": occurrence_id}}, "size": 100},
        )
        return [hit["_source"] for hit in resp.get("hits", {}).get("hits", [])]

    def upsert_value(self, occurrence_id: str, val: MarketEventValueInput) -> str:
        now = utc_now().isoformat()
        doc = val.model_dump()
        doc["occurrence_id"] = occurrence_id
        doc.setdefault("created_at", now)
        doc["updated_at"] = now
        value_id = f"{occurrence_id}_{val.value_type}_{val.label or 'default'}"
        return self._es.index_document(
            self._s.es_market_event_value_index, id=value_id, document=doc
        )["_id"]

    def upsert_values(self, occurrence_id: str, values: list[MarketEventValueInput]) -> int:
        count = 0
        for val in values:
            self.upsert_value(occurrence_id, val)
            count += 1
        return count

    # ------------------------------------------------------------------
    # Impacts
    # ------------------------------------------------------------------

    def get_impacts_for_occurrence(self, occurrence_id: str) -> list[dict]:
        resp = self._es.search(
            self._s.es_market_event_impact_index,
            {"query": {"term": {"occurrence_id": occurrence_id}}, "size": 100},
        )
        return [hit["_source"] for hit in resp.get("hits", {}).get("hits", [])]

    def upsert_impact(self, occurrence_id: str, impact: MarketEventImpactInput) -> str:
        now = utc_now().isoformat()
        doc = impact.model_dump()
        doc["occurrence_id"] = occurrence_id
        doc.setdefault("created_at", now)
        doc["updated_at"] = now
        impact_id = f"{occurrence_id}_{impact.symbol or 'none'}_{impact.asset_class or 'none'}_{impact.market or 'none'}"
        return self._es.index_document(
            self._s.es_market_event_impact_index, id=impact_id, document=doc
        )["_id"]

    def upsert_impacts(self, occurrence_id: str, impacts: list[MarketEventImpactInput]) -> int:
        count = 0
        for imp in impacts:
            self.upsert_impact(occurrence_id, imp)
            count += 1
        return count

    # ------------------------------------------------------------------
    # News Links
    # ------------------------------------------------------------------

    def get_news_links_for_occurrence(self, occurrence_id: str) -> list[dict]:
        resp = self._es.search(
            self._s.es_market_event_news_link_index,
            {"query": {"term": {"occurrence_id": occurrence_id}}, "size": 100},
        )
        return [hit["_source"] for hit in resp.get("hits", {}).get("hits", [])]

    def upsert_news_link(self, occurrence_id: str, link: MarketEventNewsLinkInput) -> str:
        now = utc_now().isoformat()
        doc = link.model_dump()
        doc["occurrence_id"] = occurrence_id
        doc.setdefault("created_at", now)
        doc["updated_at"] = now
        link_id = f"{occurrence_id}_{link.source_code or 'none'}_{link.news_id or link.url or 'none'}"
        return self._es.index_document(
            self._s.es_market_event_news_link_index, id=link_id, document=doc
        )["_id"]

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def get_analysis_for_occurrence(self, occurrence_id: str) -> list[dict]:
        resp = self._es.search(
            self._s.es_market_event_analysis_index,
            {"query": {"term": {"occurrence_id": occurrence_id}}, "size": 100},
        )
        return [hit["_source"] for hit in resp.get("hits", {}).get("hits", [])]

    # ------------------------------------------------------------------
    # Sync Runs
    # ------------------------------------------------------------------

    def create_sync_run(self, doc: dict) -> str:
        now = utc_now().isoformat()
        doc.setdefault("created_at", now)
        doc["updated_at"] = now
        result = self._es.index_document(
            self._s.es_market_event_sync_run_index, id=now + doc.get("source_code", ""), document=doc
        )
        return result["_id"]

    def update_sync_run(self, sync_run_id: str, updates: dict) -> None:
        resp = self._es.get(self._s.es_market_event_sync_run_index, sync_run_id)
        if not resp:
            return
        doc = dict(resp["_source"])
        doc.update(updates)
        doc["updated_at"] = utc_now().isoformat()
        self._es.index_document(
            self._s.es_market_event_sync_run_index, id=sync_run_id, document=doc
        )

    def list_sync_runs(
        self,
        query_body: dict | None = None,
        size: int = 50,
        from_: int = 0,
    ) -> tuple[list[dict], int]:
        body: dict[str, Any] = {
            "query": query_body or {"match_all": {}},
            "size": size,
            "from": from_,
            "sort": [{"started_at": "desc"}],
        }
        resp = self._es.search(self._s.es_market_event_sync_run_index, body)
        total = resp.get("hits", {}).get("total", {}).get("value", 0)
        items = []
        for hit in resp.get("hits", {}).get("hits", []):
            doc = dict(hit["_source"])
            doc["_id"] = hit["_id"]
            items.append(doc)
        return items, total

    # ------------------------------------------------------------------
    # Definitions
    # ------------------------------------------------------------------

    def get_definition(self, definition_id: str) -> dict | None:
        resp = self._es.get(self._s.es_market_event_definition_index, definition_id)
        if not resp:
            return None
        doc = dict(resp["_source"])
        doc["_id"] = resp["_id"]
        return doc

    def list_definitions(self, enabled_only: bool = True) -> list[dict]:
        query: dict = {"match_all": {}}
        if enabled_only:
            query = {"term": {"enabled": True}}
        resp = self._es.search(
            self._s.es_market_event_definition_index,
            {"query": query, "size": 500},
        )
        return [hit["_source"] for hit in resp.get("hits", {}).get("hits", [])]
