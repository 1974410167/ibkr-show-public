from __future__ import annotations

from datetime import datetime, timezone

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings

INVESTMENT_POLICY_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "dynamic": False,
        "properties": {
            "id": {"type": "keyword"},
            "policy_type": {"type": "keyword"},
            "symbol": {"type": "keyword"},
            "risk_profile": {"type": "keyword"},
            "asset_role": {"type": "keyword"},
            "conviction": {"type": "keyword"},
            "enabled": {"type": "boolean"},
            "user_preferred_target_position_pct": {"type": "double"},
            "user_preferred_max_position_pct": {"type": "double"},
            "user_preferred_min_position_pct": {"type": "double"},
            # Legacy PR1 fields may exist in older documents. They are kept
            # readable by the schema aliases but new writes use user_preferred_*.
            "target_position_pct": {"type": "double"},
            "max_position_pct": {"type": "double"},
            "min_position_pct": {"type": "double"},
            "ai_review_status": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "preferred_add_styles": {"type": "keyword"},
            "add_rules": {"type": "text"},
            "no_add_triggers": {"type": "text"},
            "sell_triggers": {"type": "text"},
            "hard_constraints": {"type": "text"},
            "soft_preferences": {"type": "text"},
            "notes": {"type": "text"},
            "payload": {"type": "object", "enabled": False},
        },
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InvestmentPolicyRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.index_name = settings.es_investment_policy_index

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.index_name, INVESTMENT_POLICY_INDEX_BODY)

    @staticmethod
    def symbol_document_id(symbol: str) -> str:
        return f"symbol:{symbol}"

    def get_global_policy(self) -> dict | None:
        try:
            response = self.es_client.get(index=self.index_name, id="global")
        except ESIndexNotFoundError:
            return None
        return response.get("_source") if response else None

    def upsert_global_policy(self, document: dict) -> dict:
        self._ensure_index()
        now = utc_now_iso()
        existing = self.get_global_policy() or {}
        stored = {
            **existing,
            **document,
            "id": "global",
            "policy_type": "global",
            "created_at": existing.get("created_at") or document.get("created_at") or now,
            "updated_at": now,
        }
        self.es_client.index_document(index=self.index_name, id="global", document=stored)
        return stored

    def list_symbol_policies(self, include_disabled: bool = True) -> list[dict]:
        filters: list[dict] = [{"term": {"policy_type": "symbol"}}]
        if not include_disabled:
            filters.append({"term": {"enabled": True}})
        try:
            response = self.es_client.search(
                index=self.index_name,
                body={
                    "query": {"bool": {"filter": filters}},
                    "sort": [{"symbol": {"order": "asc"}}],
                    "size": 1000,
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def get_symbol_policy(self, symbol: str) -> dict | None:
        try:
            response = self.es_client.get(index=self.index_name, id=self.symbol_document_id(symbol))
        except ESIndexNotFoundError:
            return None
        return response.get("_source") if response else None

    def upsert_symbol_policy(self, document: dict) -> dict:
        self._ensure_index()
        now = utc_now_iso()
        symbol = document["symbol"]
        document_id = self.symbol_document_id(symbol)
        existing = self.get_symbol_policy(symbol) or {}
        stored = {
            **existing,
            **document,
            "id": document_id,
            "policy_type": "symbol",
            "created_at": existing.get("created_at") or document.get("created_at") or now,
            "updated_at": now,
        }
        self.es_client.index_document(index=self.index_name, id=document_id, document=stored)
        return stored

    def disable_symbol_policy(self, symbol: str) -> dict | None:
        existing = self.get_symbol_policy(symbol)
        if existing is None:
            return None
        return self.upsert_symbol_policy({**existing, "enabled": False})
