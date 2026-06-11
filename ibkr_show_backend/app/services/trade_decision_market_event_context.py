"""Build market-event context cards for the trade decision graph."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agents.trade_decision_cards import (
    CardStance,
    MarketEventContextCard,
    build_fallback_market_event_context_card,
)

MARKET_EVENT_TOOL_NAME = "market_event_query_service.get_symbol_events"
_IMPORTANCE_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
_MACRO_ASSET_CLASSES = {"EQUITY", "EQUITIES", "RATES", "RATE", "BOND", "BONDS", "FX", "CRYPTO", "COMMODITY"}
_MACRO_EVENT_TYPES = {
    "CPI",
    "PCE",
    "NONFARM_PAYROLLS",
    "FOMC",
    "FOMC_RATE_DECISION",
    "RATE_DECISION",
    "GDP",
    "PMI",
    "ISM_MANUFACTURING_PMI",
    "ISM_SERVICES_PMI",
    "INFLATION",
}


class TradeDecisionMarketEventContextBuilder:
    """Query market-event facts and convert them into a trade decision card."""

    def __init__(self, market_event_query_service: Any, days: int = 30, include_macro: bool = True) -> None:
        self.market_event_query_service = market_event_query_service
        self.days = days
        self.include_macro = include_macro

    def build(self, symbol: str, decision_type: str) -> tuple[MarketEventContextCard, dict]:
        metadata: dict[str, Any] = {
            "queried_symbol": symbol,
            "query_days": self.days,
            "include_macro": self.include_macro,
            "tool_name": MARKET_EVENT_TOOL_NAME,
            "fallback_used": False,
            "fallback_reason": None,
        }
        if self.market_event_query_service is None:
            card = build_fallback_market_event_context_card(
                symbol,
                decision_type,
                "market_event_query_service_unavailable",
            )
            card.data_limitations = ["market_event_query_service_unavailable"]
            metadata.update({
                "event_count": 0,
                "macro_event_count": 0,
                "symbol_event_count": 0,
                "risk_level": "unknown",
                "fallback_used": True,
                "fallback_reason": "market_event_query_service_unavailable",
                "query_count": 0,
            })
            return card, metadata

        primary_symbol = (symbol or "").upper()
        base_symbol = _base_symbol(primary_symbol)
        query_symbols = [primary_symbol]
        if base_symbol and base_symbol != primary_symbol:
            query_symbols.append(base_symbol)

        try:
            items: list[Any] = []
            for query_symbol in query_symbols:
                result = self.market_event_query_service.get_symbol_events(
                    query_symbol,
                    days=self.days,
                    include_macro=self.include_macro,
                )
                items.extend(list(getattr(result, "items", []) or []))

            events = _dedupe_events(items)
            event_dicts = [_event_to_dict(item) for item in events]
            event_dicts = sorted(event_dicts, key=_event_sort_key)
            symbol_events = [e for e in event_dicts if _is_symbol_event(e, primary_symbol, base_symbol)]
            macro_events = [e for e in event_dicts if _is_macro_event(e)]
            upcoming_events = event_dicts[:10]
            symbol_events = symbol_events[:10]
            macro_events = macro_events[:10]
            risk_level = _risk_level(event_dicts)

            card = MarketEventContextCard(
                card_type="market_event_context",
                symbol=symbol,
                decision_type=decision_type,
                summary=_summary(symbol, symbol_events, macro_events, event_dicts, self.days),
                score=0,
                max_score=0,
                stance=CardStance.INSUFFICIENT_DATA,
                risk_level=risk_level,
                upcoming_events=upcoming_events,
                macro_events=macro_events,
                symbol_events=symbol_events,
                key_points=_key_points(event_dicts, macro_events, self.days),
                risks=_risks(event_dicts, risk_level),
                data_limitations=[] if event_dicts else [],
                evidence_quality="high" if event_dicts else "medium",
                source_tools=[MARKET_EVENT_TOOL_NAME],
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            metadata.update({
                "event_count": len(event_dicts),
                "macro_event_count": len(macro_events),
                "symbol_event_count": len(symbol_events),
                "risk_level": risk_level,
                "query_count": len(query_symbols),
                "query_symbols": query_symbols,
            })
            return card, metadata
        except Exception as exc:
            error_msg = str(exc)[:200]
            card = build_fallback_market_event_context_card(
                symbol,
                decision_type,
                f"market_event_query_failed: {error_msg}",
            )
            card.data_limitations = [f"market_event_query_failed: {error_msg}"]
            card.risk_level = "unknown"
            card.evidence_quality = "low"
            card.source_tools = [MARKET_EVENT_TOOL_NAME]
            metadata.update({
                "event_count": 0,
                "macro_event_count": 0,
                "symbol_event_count": 0,
                "risk_level": "unknown",
                "fallback_used": True,
                "fallback_reason": f"market_event_query_failed: {error_msg}",
                "query_count": len(query_symbols),
                "query_symbols": query_symbols,
            })
            return card, metadata


def _base_symbol(symbol: str) -> str:
    return symbol.split(".", 1)[0].upper() if symbol else ""


def _dedupe_events(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    deduped: list[Any] = []
    for item in items:
        event_id = str(getattr(item, "id", "") or "")
        if not event_id:
            event_id = str(_event_to_dict(item).get("title") or id(item))
        if event_id in seen:
            continue
        seen.add(event_id)
        deduped.append(item)
    return deduped


def _event_to_dict(item: Any) -> dict:
    if hasattr(item, "model_dump"):
        raw = item.model_dump(mode="json")
    elif isinstance(item, dict):
        raw = item
    else:
        raw = {
            key: getattr(item, key, None)
            for key in (
                "id", "title", "summary", "category", "event_type", "status", "importance",
                "source_code", "country", "market", "symbols", "asset_classes", "scheduled_at",
                "scheduled_timezone", "period", "is_all_day", "is_confirmed_time",
                "has_actual_value", "has_forecast_value", "values", "impacts", "source_url",
            )
        }

    allowed = (
        "id", "title", "summary", "category", "event_type", "status", "importance",
        "source_code", "country", "market", "symbols", "asset_classes", "scheduled_at",
        "scheduled_timezone", "period", "is_all_day", "is_confirmed_time",
        "has_actual_value", "has_forecast_value", "values", "impacts", "source_url",
    )
    return {key: _json_safe(raw.get(key)) for key in allowed}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    return str(value)


def _event_sort_key(event: dict) -> tuple[str, int]:
    scheduled_at = str(event.get("scheduled_at") or "")
    importance = str(event.get("importance") or "").upper()
    return scheduled_at, _IMPORTANCE_RANK.get(importance, 99)


def _is_symbol_event(event: dict, primary_symbol: str, base_symbol: str) -> bool:
    symbols = {str(s).upper() for s in (event.get("symbols") or [])}
    if primary_symbol and primary_symbol in symbols:
        return True
    if base_symbol and base_symbol in symbols:
        return True
    category = str(event.get("category") or "").upper()
    return category not in {"MACRO", "FED", "MARKET"} and bool(symbols)


def _is_macro_event(event: dict) -> bool:
    category = str(event.get("category") or "").upper()
    event_type = str(event.get("event_type") or "").upper()
    asset_classes = {str(a).upper() for a in (event.get("asset_classes") or [])}
    return category == "MACRO" or bool(asset_classes & _MACRO_ASSET_CLASSES) or event_type in _MACRO_EVENT_TYPES


def _risk_level(events: list[dict]) -> str:
    importances = {str(e.get("importance") or "").upper() for e in events}
    if "CRITICAL" in importances:
        return "critical"
    if "HIGH" in importances:
        return "high"
    if "MEDIUM" in importances:
        return "medium"
    return "low"


def _summary(symbol: str, symbol_events: list[dict], macro_events: list[dict], events: list[dict], days: int) -> str:
    if symbol_events:
        return f"未来 {days} 天存在 {len(symbol_events)} 个与 {symbol} 相关的重点事件，并叠加 {len(macro_events)} 个高重要性宏观事件。"
    if macro_events:
        return f"未来 {days} 天未发现明确标的级重点事件，但存在 {len(macro_events)} 个高重要性宏观事件，可能影响市场风险偏好。"
    if not events:
        return f"未来 {days} 天未发现明确重点事件，事件日历暂不构成主要交易约束。"
    return f"未来 {days} 天存在 {len(events)} 个市场事件，但未发现明确标的级重点事件。"


def _key_points(events: list[dict], macro_events: list[dict], days: int) -> list[str]:
    if not events:
        return [f"未来 {days} 天未发现明确重点事件"]
    points = []
    for event in events[:3]:
        date = str(event.get("scheduled_at") or "")[:10]
        title = event.get("title") or event.get("event_type") or "Market event"
        importance = event.get("importance") or "UNKNOWN"
        points.append(f"{date} {title}，importance={importance}")
    if macro_events and len(macro_events) == len(events):
        points.append("当前事件窗口主要来自高重要性宏观风险")
    return points


def _risks(events: list[dict], risk_level: str) -> list[str]:
    risks: list[str] = []
    event_types = {str(e.get("event_type") or "").upper() for e in events}
    if risk_level in {"high", "critical"}:
        risks.append("未来存在高重要性事件，交易计划应考虑事件落地前后的波动风险")
    if event_types & {"FOMC_RATE_DECISION", "FOMC", "CPI", "PCE", "NONFARM_PAYROLLS"}:
        risks.append("宏观数据或利率事件可能影响成长股估值和市场风险偏好")
    if "EARNINGS" in event_types:
        risks.append("财报事件可能带来跳空波动，需要设置复查条件")
    return risks
