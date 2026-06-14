from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings

TRADE_DECISION_INDEX_BODY = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        # Multi-agent runs accumulate many nested fields (per-node trace, per-card
        # structured_output, per-tool_call detail). The default 1500 limit was
        # blowing up persist_decision once debate + trade_plan cards landed.
        "index.mapping.total_fields.limit": 5000,
    },
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "decision_type": {"type": "keyword"},
            "symbol": {"type": "keyword"},
            "user_question": {"type": "text"},
            "overall_score": {"type": "double"},
            "rating": {"type": "keyword"},
            "action": {"type": "keyword"},
            "confidence": {"type": "keyword"},
            "decision_summary": {"type": "text"},
            "key_reasons": {"type": "text"},
            "major_risks": {"type": "text"},
            "review_warnings": {"type": "text"},
            "data_limitations": {"type": "text"},
            "raw_llm_response": {"type": "text", "index": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "fallback_used": {"type": "boolean"},
            "fallback_reason": {"type": "text", "index": False},
            # Heavy nested objects are stored as-is in _source but not indexed.
            # Filtering happens on top-level keyword/date fields above; analytics
            # reads decision_quality/etc. straight from _source after a search.
            "score_detail": {"type": "object", "enabled": False},
            "position_advice": {"type": "object", "enabled": False},
            "execution_plan": {"type": "object", "enabled": False},
            "run_trace": {"type": "object", "enabled": False},
            "run_trace_summary": {"type": "object", "enabled": False},
            "evidence_pack": {"type": "object", "enabled": False},
            "evidence_summary": {"type": "object", "enabled": False},
            "card_pack": {"type": "object", "enabled": False},
            "model_provider_snapshot": {"type": "object", "enabled": False},
            "data_source_summary": {"type": "object", "enabled": False},
            "metadata": {"type": "object", "enabled": False},
            "decision_quality": {"type": "object", "enabled": False},
            "asset_debate": {"type": "object", "enabled": False},
            "trade_plan": {"type": "object", "enabled": False},
            "risk_gate": {"type": "object", "enabled": False},
            "llm_error_summary": {"type": "object", "enabled": False},
            "agent_run_trace": {"type": "object", "enabled": False},
            "agent_replay": {"type": "object", "enabled": False},
        }
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TradeDecisionRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings
        self._settings_bumped = False

    def _ensure_index(self) -> None:
        index = self.settings.es_trade_decision_index
        self.es_client.create_index_if_missing(index, TRADE_DECISION_INDEX_BODY)
        # The pre-multi-agent index may have been created with the default
        # 1500-field cap. Once new card_pack + run_trace mappings push past
        # that limit, persist_decision fails with document_parsing_exception.
        # Bump the limit on existing indexes so writes survive without a
        # reindex; the new mapping above already disables auto-indexing for
        # the heavy nested fields going forward.
        if not self._settings_bumped:
            try:
                self.es_client.put_index_settings(
                    index,
                    {"index": {"mapping": {"total_fields": {"limit": 5000}}}},
                )
            except Exception:
                pass
            self._settings_bumped = True

    def save_decision(self, document: dict) -> dict:
        self._ensure_index()
        now = utc_now_iso()
        decision_id = document.get("id") or str(uuid4())
        evidence_pack = document.get("evidence_pack")
        card_pack = document.get("card_pack")
        stored = {
            **document,
            "id": decision_id,
            "evidence_pack": _compact_evidence_pack_for_storage(evidence_pack),
            "card_pack": _compact_card_pack_for_storage(card_pack),
            "created_at": document.get("created_at") or now,
            "updated_at": now,
        }
        self.es_client.index_document(index=self.settings.es_trade_decision_index, id=decision_id, document=stored)
        return stored

    def get_decision(self, decision_id: str) -> dict | None:
        try:
            response = self.es_client.get(index=self.settings.es_trade_decision_index, id=decision_id)
        except ESIndexNotFoundError:
            return None
        return response.get("_source") if response else None

    def list_recent_decisions(self, limit: int, decision_type: str | None = None) -> list[dict]:
        filters = []
        if decision_type:
            filters.append({"term": {"decision_type": decision_type}})
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_decision_index,
                body={
                    "query": {"bool": {"filter": filters or [{"match_all": {}}]}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": limit,
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def list_recent_decisions_for_quality(self, limit: int = 200, days: int | None = None) -> list[dict]:
        filters = []
        if days is not None:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            filters.append({"range": {"created_at": {"gte": since.isoformat()}}})
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_decision_index,
                body={
                    "query": {"bool": {"filter": filters or [{"match_all": {}}]}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": limit,
                    "_source": [
                        "id",
                        "symbol",
                        "created_at",
                        "action",
                        "decision_quality",
                        "risk_gate",
                        "trade_plan",
                        "card_pack",
                        "run_trace",
                        "metadata",
                    ],
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def list_recent_decisions_for_outcome(
        self,
        *,
        limit: int = 500,
        days: int | None = 90,
        symbol: str | None = None,
        decision_type: str | None = None,
    ) -> list[dict]:
        filters = []
        if days is not None:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            filters.append({"range": {"created_at": {"gte": since.isoformat()}}})
        if symbol:
            filters.append({"term": {"symbol": symbol}})
        if decision_type:
            filters.append({"term": {"decision_type": decision_type}})
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_decision_index,
                body={
                    "query": {"bool": {"filter": filters or [{"match_all": {}}]}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": limit,
                    "_source": [
                        "id",
                        "symbol",
                        "decision_type",
                        "created_at",
                        "action",
                        "draft_action",
                        "risk_adjusted_action",
                        "final_action",
                        "trade_plan",
                        "risk_gate",
                        "position_advice",
                        "user_investment_policy_summary",
                        "ai_policy_assessment",
                    ],
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def list_symbol_decisions(self, symbol: str, limit: int) -> list[dict]:
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_decision_index,
                body={
                    "query": {"bool": {"filter": [{"term": {"symbol": symbol}}]}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": limit,
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]


def _compact_evidence_pack_for_storage(evidence_pack: object) -> dict:
    if not isinstance(evidence_pack, dict):
        return {}

    account_context = _dict_value(evidence_pack.get("account_context"))
    position_context = _dict_value(evidence_pack.get("position_context"))
    trade_history_context = _dict_value(evidence_pack.get("trade_history_context"))
    review_context = _dict_value(evidence_pack.get("review_context"))
    company_context = _dict_value(evidence_pack.get("company_context"))
    valuation_context = _dict_value(evidence_pack.get("valuation_context"))
    external_events = _dict_value(evidence_pack.get("external_events"))
    static_info = _dict_value(company_context.get("static_info"))

    return {
        "decision_type": evidence_pack.get("decision_type"),
        "objective": evidence_pack.get("objective") if isinstance(evidence_pack.get("objective"), dict) else {},
        "symbol": evidence_pack.get("symbol"),
        "user_question": evidence_pack.get("user_question"),
        "data_sources": evidence_pack.get("data_sources") if isinstance(evidence_pack.get("data_sources"), dict) else {},
        "account_context": {
            "source": account_context.get("source"),
            "net_liquidation": account_context.get("net_liquidation"),
            "cash": account_context.get("cash"),
            "cash_ratio": account_context.get("cash_ratio"),
            "cash_equivalents_value": account_context.get("cash_equivalents_value"),
            "cash_equivalents_ratio": account_context.get("cash_equivalents_ratio"),
            "cash_equivalent_positions": _list_of_selected_dicts(
                account_context.get("cash_equivalent_positions"),
                ("symbol", "position_value", "position_pct", "liquidity_note"),
                limit=10,
            ),
            "deployable_liquidity": account_context.get("deployable_liquidity"),
            "deployable_liquidity_ratio": account_context.get("deployable_liquidity_ratio"),
            "total_position_value": account_context.get("total_position_value"),
            "position_concentration": account_context.get("position_concentration"),
            "risk_position_concentration_ex_cash_equivalents": account_context.get("risk_position_concentration_ex_cash_equivalents"),
            "top_positions": _list_of_selected_dicts(
                account_context.get("top_positions"),
                ("symbol", "position_value", "position_pct"),
                limit=10,
            ),
        },
        "position_context": _select_keys(
            position_context,
            (
                "source",
                "is_holding",
                "quantity",
                "avg_cost",
                "current_price",
                "market_value",
                "position_pct",
                "unrealized_pnl",
                "unrealized_pnl_pct",
                "realized_pnl",
            ),
        ),
        "trade_history_context": {
            "source": trade_history_context.get("source"),
            "first_buy_date": trade_history_context.get("first_buy_date"),
            "last_trade_date": trade_history_context.get("last_trade_date"),
            "holding_days": trade_history_context.get("holding_days"),
            "recent_trades": _list_of_selected_dicts(
                trade_history_context.get("recent_trades"),
                ("trade_id", "date", "side", "quantity", "price", "amount", "commission", "realized_pnl"),
                limit=20,
            ),
        },
        "review_context": {
            "source": review_context.get("source"),
            "symbol_latest_review": _select_keys(
                _dict_value(review_context.get("symbol_latest_review")),
                ("id", "overall_score", "rating", "summary", "mistake_tags", "created_at"),
            ),
            "symbol_mistake_tags": _string_list(review_context.get("symbol_mistake_tags"), limit=20),
            "global_mistake_summary": _list_of_selected_dicts(
                review_context.get("global_mistake_summary"),
                ("tag", "count"),
                limit=20,
            ),
        },
        "company_context": {
            "source": company_context.get("source"),
            "static_info": _select_keys(
                static_info,
                ("symbol", "name", "name_en", "stock_name", "currency", "exchange", "industry"),
            ),
        },
        "valuation_context": {
            "source": valuation_context.get("source"),
            "quote": _select_keys(
                _dict_value(valuation_context.get("quote")),
                ("symbol", "last_done", "last", "prev_close", "change_rate", "change_percentage", "volume", "turnover"),
            ),
            "valuation_metrics": _select_keys(
                _dict_value(valuation_context.get("valuation_metrics")),
                (
                    "pe_ttm_ratio",
                    "pb_ratio",
                    "dividend_ratio_ttm",
                    "total_market_value",
                    "eps",
                    "eps_ttm",
                    "bps",
                    "dividend_yield",
                    "total_shares",
                    "circulating_shares",
                ),
            ),
        },
        "market_context": _select_keys(_dict_value(evidence_pack.get("market_context")), ("source",)),
        "external_events": {
            "source": external_events.get("source"),
            "news": _event_summaries(external_events.get("news"), limit=10),
            "filings": _event_summaries(external_events.get("filings"), limit=10),
            "topics": _event_summaries(external_events.get("topics"), limit=10),
            "warnings": _string_list(external_events.get("warnings"), limit=20),
        },
        "tool_trace": _dict_value(evidence_pack).get("tool_trace") if isinstance(_dict_value(evidence_pack).get("tool_trace"), list) else [],
        "data_quality": {
            "warnings": _string_list(_dict_value(evidence_pack.get("data_quality")).get("warnings"), limit=30),
        },
    }


def _dict_value(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _select_keys(source: dict, keys: tuple[str, ...]) -> dict:
    return {key: source.get(key) for key in keys if key in source}


def _list_of_selected_dicts(value: object, keys: tuple[str, ...], *, limit: int) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [_select_keys(_dict_value(item), keys) for item in value[:limit] if isinstance(item, dict)]


def _event_summaries(value: object, *, limit: int) -> list[dict]:
    if not isinstance(value, list):
        return []
    keys = ("id", "title", "summary", "url", "published_at", "released_at")
    return [_select_keys(_dict_value(item), keys) for item in value[:limit] if isinstance(item, dict)]


def _string_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:limit] if item is not None]


def _compact_card_pack_for_storage(card_pack: object) -> dict:
    """Compact card pack for storage, keeping essential card data."""
    if not isinstance(card_pack, dict):
        return {}

    # Keep full card data but trim large fields
    account_fit = _dict_value(card_pack.get("account_fit_card"))
    market_trend = _dict_value(card_pack.get("market_trend_card"))
    fundamental = _dict_value(card_pack.get("fundamental_valuation_card"))
    event = _dict_value(card_pack.get("event_catalyst_card"))
    risk_reward = _dict_value(card_pack.get("risk_reward_card"))
    snapshot = _dict_value(card_pack.get("account_fact_snapshot"))
    traces = card_pack.get("subagent_traces") if isinstance(card_pack.get("subagent_traces"), list) else []

    # Trim evidence lists
    for card_dict in [account_fit, market_trend, fundamental, event, risk_reward]:
        if isinstance(card_dict, dict):
            evidence = card_dict.get("evidence")
            if isinstance(evidence, list):
                card_dict["evidence"] = evidence[:10]  # max 10 evidence items

    return {
        "decision_type": card_pack.get("decision_type"),
        "symbol": card_pack.get("symbol"),
        "data_quality_summary": card_pack.get("data_quality_summary"),
        "account_fit_card": _trim_card_summary(account_fit),
        "market_trend_card": _trim_card_summary(market_trend),
        "fundamental_valuation_card": _trim_card_summary(fundamental),
        "event_catalyst_card": _trim_card_summary(event),
        "risk_reward_card": _trim_card_summary(risk_reward),
        "account_fact_snapshot": {
            "decision_type": snapshot.get("decision_type"),
            "symbol": snapshot.get("symbol"),
            "normalized_symbol": snapshot.get("normalized_symbol"),
            "account_context": _select_keys(snapshot.get("account_context", {}), (
                "net_liquidation", "cash", "deployable_liquidity", "deployable_liquidity_ratio",
                "total_position_value", "position_concentration",
                "risk_position_concentration_ex_cash_equivalents",
            )),
            "position_context": _select_keys(snapshot.get("position_context", {}), (
                "is_holding", "quantity", "avg_cost", "current_price", "market_value",
                "position_pct", "unrealized_pnl", "unrealized_pnl_pct", "realized_pnl",
            )),
            "trade_history_context": _select_keys(snapshot.get("trade_history_context", {}), (
                "recent_trades", "first_buy_date", "last_trade_date", "holding_days",
            )),
            "review_context": _select_keys(snapshot.get("review_context", {}), (
                "symbol_latest_review", "symbol_mistake_tags", "global_mistake_summary",
            )),
        },
        "subagent_traces": [
            {
                "sub_agent_name": t.get("sub_agent_name") if isinstance(t, dict) else str(t),
                "status": t.get("status") if isinstance(t, dict) else "unknown",
                "elapsed_ms": t.get("elapsed_ms") if isinstance(t, dict) else 0,
                "rounds_used": t.get("rounds_used") if isinstance(t, dict) else 0,
                "tools_called": t.get("tools_called") if isinstance(t, dict) else [],
                "fallback_used": t.get("fallback_used") if isinstance(t, dict) else False,
            }
            for t in traces[:10]
        ],
    }


_TRIM_TEXT_KEYS = frozenset({"summary"})
_TRIM_LIST_KEYS = frozenset({"key_points", "risks", "opportunities", "evidence", "data_limitations", "source_tools", "key_events", "risk_events"})


def _trim_card_summary(card: dict) -> dict:
    """Trim card for storage, preserving all card-type-specific fields."""
    if not isinstance(card, dict):
        return {}
    result: dict = {}
    for key, value in card.items():
        if key in _TRIM_TEXT_KEYS:
            result[key] = _truncate_str(value, 300)
        elif key in _TRIM_LIST_KEYS:
            result[key] = _string_list(value, limit=10 if key == "source_tools" else 5)
        else:
            result[key] = value
    return result


def _truncate_str(value: str, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value[:limit] if len(value) > limit else value
