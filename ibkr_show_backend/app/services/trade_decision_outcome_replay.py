from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings
from app.schemas.trade_decision import (
    TradeDecisionOutcomeItem,
    TradeDecisionOutcomeListResponse,
    TradeDecisionOutcomeSummary,
)
from app.services.longbridge_service import normalize_longbridge_symbol
from app.services.trade_decision_repository import TradeDecisionRepository

ADD_LIKE_ACTIONS = {"add", "add_small", "add_batch", "add_on_pullback", "add_right_side"}
REDUCE_LIKE_ACTIONS = {"reduce", "reduce_batch", "reduce_now", "trim_on_rebound", "sell", "sell_thesis_broken"}
HOLD_LIKE_ACTIONS = {"hold", "hold_no_add", "wait", "watchlist", "avoid", "panic_blocked"}

GOOD_RETURN_THRESHOLD = 0.0
BAD_ADD_RETURN_20D_THRESHOLD = -0.05
BAD_ADD_DRAWDOWN_20D_THRESHOLD = -0.08
MISSED_UPSIDE_RETURN_20D_THRESHOLD = 0.08
AVOIDED_LOSS_RETURN_20D_THRESHOLD = -0.05
DEFAULT_HORIZONS = (1, 5, 20)


@dataclass
class PriceOutcome:
    decision_price: float | None = None
    prices_after: dict[int, float | None] = field(default_factory=dict)
    returns: dict[int, float | None] = field(default_factory=dict)
    max_drawdown_20d: float | None = None
    max_runup_20d: float | None = None
    price_data_status: str = "unknown"
    data_limitations: list[str] = field(default_factory=list)


class TradeDecisionOutcomePriceProvider:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def evaluate(self, symbol: str, decision_date: date | None, horizons: list[int]) -> PriceOutcome:
        if decision_date is None:
            return PriceOutcome(price_data_status="missing", data_limitations=["decision_date_missing"])

        normalized = _normalize_symbol_for_price(symbol)
        max_horizon = max(horizons or list(DEFAULT_HORIZONS))
        end_date = decision_date + timedelta(days=max(45, max_horizon * 4))
        filters = [
            {"term": {"symbol": normalized}},
            {"range": {"report_date": {"gte": decision_date.isoformat(), "lte": end_date.isoformat()}}},
        ]
        try:
            response = self.es_client.search(
                index=self.settings.es_price_history_index,
                body={
                    "query": {"bool": {"filter": filters}},
                    "sort": [{"report_date": {"order": "asc", "missing": "_last"}}],
                    "size": 200,
                    "_source": ["symbol", "report_date", "open_price", "high_price", "low_price", "close_price"],
                },
            )
        except ESIndexNotFoundError:
            return PriceOutcome(price_data_status="missing", data_limitations=["price_history_index_missing"])

        bars = [_dict(hit.get("_source")) for hit in response.get("hits", {}).get("hits", [])]
        bars = [bar for bar in bars if _float(bar.get("close_price")) is not None and str(bar.get("report_date") or "")]
        if not bars:
            return PriceOutcome(price_data_status="missing", data_limitations=[f"price_missing:{normalized}"])

        decision_index = 0
        decision_bar = bars[decision_index]
        decision_price = _float(decision_bar.get("close_price"))
        result = PriceOutcome(decision_price=decision_price, price_data_status="ok")
        first_date = _parse_date(decision_bar.get("report_date"))
        if first_date and first_date > decision_date:
            result.price_data_status = "shifted"
            result.data_limitations.append(f"decision_date_price_shifted:{decision_date.isoformat()}->{first_date.isoformat()}")

        if decision_price is None or decision_price <= 0:
            result.price_data_status = "missing"
            result.data_limitations.append("decision_price_invalid")
            return result

        for horizon in horizons:
            target_index = decision_index + horizon
            if target_index >= len(bars):
                result.prices_after[horizon] = None
                result.returns[horizon] = None
                result.data_limitations.append(f"insufficient_price_history:{horizon}d")
                continue
            price = _float(bars[target_index].get("close_price"))
            result.prices_after[horizon] = price
            result.returns[horizon] = _return_pct(decision_price, price)

        lookahead_bars = bars[decision_index + 1: decision_index + 21]
        if len(lookahead_bars) < 20:
            result.data_limitations.append("insufficient_price_history:20d_drawdown")
        if lookahead_bars:
            lows = [_float(bar.get("low_price")) or _float(bar.get("close_price")) for bar in lookahead_bars]
            highs = [_float(bar.get("high_price")) or _float(bar.get("close_price")) for bar in lookahead_bars]
            lows = [value for value in lows if value is not None]
            highs = [value for value in highs if value is not None]
            result.max_drawdown_20d = _return_pct(decision_price, min(lows) if lows else None)
            result.max_runup_20d = _return_pct(decision_price, max(highs) if highs else None)
        return result


class TradeDecisionOutcomeReplayService:
    def __init__(
        self,
        repository: TradeDecisionRepository,
        price_provider: TradeDecisionOutcomePriceProvider,
    ) -> None:
        self.repository = repository
        self.price_provider = price_provider

    def build_outcomes(
        self,
        *,
        days: int = 90,
        limit: int = 500,
        symbol: str | None = None,
        decision_type: str | None = None,
        horizons: list[int] | None = None,
        action_group: str | None = None,
        outcome_label: str | None = None,
    ) -> TradeDecisionOutcomeListResponse:
        normalized_symbol = normalize_longbridge_symbol(symbol) if symbol else None
        selected_horizons = _normalize_horizons(horizons)
        docs = self.repository.list_recent_decisions_for_outcome(
            limit=limit,
            days=days,
            symbol=normalized_symbol,
            decision_type=decision_type,
        )
        items = [self.evaluate_document(doc, horizons=selected_horizons) for doc in docs]
        if action_group:
            items = [item for item in items if item.action_group == action_group]
        if outcome_label:
            items = [item for item in items if item.outcome_label == outcome_label]
        summary = summarize_outcomes(items)
        return TradeDecisionOutcomeListResponse(items=items, summary=summary)

    def get_outcome(self, decision_id: str, horizons: list[int] | None = None) -> TradeDecisionOutcomeItem | None:
        doc = self.repository.get_decision(decision_id)
        if doc is None:
            return None
        return self.evaluate_document(doc, horizons=_normalize_horizons(horizons))

    def evaluate_document(self, doc: dict, *, horizons: list[int]) -> TradeDecisionOutcomeItem:
        created_at = str(doc.get("created_at") or "")
        decision_date = _decision_date(created_at)
        final_action = str(doc.get("final_action") or doc.get("action") or "").strip().lower()
        draft_action = str(doc.get("draft_action") or _dict(doc.get("trade_plan")).get("portfolio_action") or "").strip().lower() or None
        risk_adjusted_action = str(doc.get("risk_adjusted_action") or final_action or "").strip().lower() or None
        action_group = action_group_for(final_action)
        price = self.price_provider.evaluate(str(doc.get("symbol") or ""), decision_date, horizons)
        assessment = _dict(doc.get("ai_policy_assessment"))
        user_policy = _dict(doc.get("user_investment_policy_summary"))
        label, reason = label_outcome(action_group, price.returns.get(5), price.returns.get(20), price.max_drawdown_20d)
        return TradeDecisionOutcomeItem(
            decision_id=str(doc.get("id") or ""),
            symbol=str(doc.get("symbol") or ""),
            decision_type=str(doc.get("decision_type") or ""),
            created_at=created_at,
            decision_date=decision_date.isoformat() if decision_date else None,
            draft_action=draft_action,
            risk_adjusted_action=risk_adjusted_action,
            final_action=final_action or None,
            action_group=action_group,
            ai_position_stance=_str_or_none(assessment.get("ai_position_stance")),
            ai_recommended_action_bias=_str_or_none(assessment.get("recommended_action_bias")),
            ai_recommended_target_position_pct=_float(assessment.get("ai_recommended_target_position_pct")),
            ai_recommended_max_position_pct=_float(assessment.get("ai_recommended_max_position_pct")),
            user_preferred_target_position_pct=_float(user_policy.get("user_preferred_target_position_pct")),
            decision_price=price.decision_price,
            price_after_1d=price.prices_after.get(1),
            price_after_5d=price.prices_after.get(5),
            price_after_20d=price.prices_after.get(20),
            return_1d=price.returns.get(1),
            return_5d=price.returns.get(5),
            return_20d=price.returns.get(20),
            max_drawdown_20d=price.max_drawdown_20d,
            max_runup_20d=price.max_runup_20d,
            price_data_status=price.price_data_status,
            outcome_label=label,
            outcome_reason=reason,
            data_limitations=price.data_limitations,
        )


def summarize_outcomes(items: list[TradeDecisionOutcomeItem]) -> TradeDecisionOutcomeSummary:
    groups: dict[str, list[TradeDecisionOutcomeItem]] = defaultdict(list)
    label_counter: Counter[str] = Counter()
    group_counter: Counter[str] = Counter()
    symbol_counter: Counter[str] = Counter()
    final_action_counter: Counter[str] = Counter()
    ai_bias_counter: Counter[str] = Counter()
    ai_stance_counter: Counter[str] = Counter()
    data_limitations: Counter[str] = Counter()
    value_points = 0
    value_count = 0

    for item in items:
        groups[item.action_group].append(item)
        label_counter[item.outcome_label] += 1
        group_counter[item.action_group] += 1
        symbol_counter[item.symbol or "unknown"] += 1
        final_action_counter[item.final_action or "unknown"] += 1
        ai_bias_counter[item.ai_recommended_action_bias or "unknown"] += 1
        ai_stance_counter[item.ai_position_stance or "unknown"] += 1
        data_limitations.update(item.data_limitations)
        point = _label_value(item.outcome_label)
        if point is not None:
            value_points += point
            value_count += 1

    evaluated = [item for item in items if item.outcome_label != "pending" and item.price_data_status != "missing"]
    missing_price_count = sum(1 for item in items if item.price_data_status == "missing")
    pending_count = sum(1 for item in items if item.outcome_label == "pending")

    return TradeDecisionOutcomeSummary(
        version="trade_decision_outcome_replay_v1",
        total_count=len(items),
        evaluated_count=len(evaluated),
        pending_count=pending_count,
        missing_price_count=missing_price_count,
        add_like_count=len(groups["add_like"]),
        hold_like_count=len(groups["hold_like"]),
        reduce_like_count=len(groups["reduce_like"]),
        add_like_avg_return_1d=_avg_return(groups["add_like"], "return_1d"),
        add_like_avg_return_5d=_avg_return(groups["add_like"], "return_5d"),
        add_like_avg_return_20d=_avg_return(groups["add_like"], "return_20d"),
        hold_like_avg_return_1d=_avg_return(groups["hold_like"], "return_1d"),
        hold_like_avg_return_5d=_avg_return(groups["hold_like"], "return_5d"),
        hold_like_avg_return_20d=_avg_return(groups["hold_like"], "return_20d"),
        reduce_like_avg_return_1d=_avg_return(groups["reduce_like"], "return_1d"),
        reduce_like_avg_return_5d=_avg_return(groups["reduce_like"], "return_5d"),
        reduce_like_avg_return_20d=_avg_return(groups["reduce_like"], "return_20d"),
        add_like_win_rate_5d=_win_rate(groups["add_like"], "return_5d"),
        add_like_win_rate_20d=_win_rate(groups["add_like"], "return_20d"),
        bad_add_count=label_counter["bad_add"],
        missed_upside_count=label_counter["missed_upside"],
        avoided_loss_count=label_counter["avoided_loss"],
        sold_too_early_count=label_counter["sold_too_early"],
        missed_ai_add_opportunity_count=sum(1 for item in items if is_missed_ai_add_opportunity(item)),
        calibrated_action_success_count=sum(1 for item in items if is_calibrated_action_success(item)),
        risk_gate_avoided_loss_count=sum(1 for item in items if is_risk_gate_avoided_loss(item)),
        risk_gate_missed_upside_count=sum(1 for item in items if is_risk_gate_missed_upside(item)),
        action_value_score=round(value_points / value_count, 4) if value_count else None,
        outcome_label_distribution=_top_items(label_counter),
        action_group_distribution=_top_items(group_counter),
        by_symbol=_top_items(symbol_counter),
        by_final_action=_top_items(final_action_counter),
        by_ai_recommended_action_bias=_top_items(ai_bias_counter),
        by_ai_position_stance=_top_items(ai_stance_counter),
        top_good_decisions=_top_decisions(items, labels={"good_action", "avoided_loss"}, reverse=True),
        top_bad_decisions=_top_decisions(items, labels={"bad_add", "sold_too_early"}, reverse=False),
        top_missed_upside_decisions=_top_decisions(items, labels={"missed_upside"}, reverse=True),
        generated_at=datetime.now(timezone.utc).isoformat(),
        data_limitations=[item for item, _ in data_limitations.most_common(10)],
    )


def action_group_for(action: str | None) -> str:
    normalized = str(action or "").strip().lower()
    if normalized in ADD_LIKE_ACTIONS:
        return "add_like"
    if normalized in REDUCE_LIKE_ACTIONS:
        return "reduce_like"
    if normalized in HOLD_LIKE_ACTIONS:
        return "hold_like"
    return "unknown"


def label_outcome(
    action_group: str,
    return_5d: float | None,
    return_20d: float | None,
    max_drawdown_20d: float | None,
) -> tuple[str, str]:
    if return_20d is None:
        return "pending", "20d forward price is not available yet"
    if action_group == "add_like":
        if return_20d < BAD_ADD_RETURN_20D_THRESHOLD or (
            max_drawdown_20d is not None and max_drawdown_20d < BAD_ADD_DRAWDOWN_20D_THRESHOLD
        ):
            return "bad_add", "add-like action was followed by a large loss or drawdown"
        if (return_5d is not None and return_5d > GOOD_RETURN_THRESHOLD) or return_20d > GOOD_RETURN_THRESHOLD:
            return "good_action", "add-like action was followed by positive forward return"
        return "neutral_add", "add-like action had limited forward edge"
    if action_group == "hold_like":
        if return_20d > MISSED_UPSIDE_RETURN_20D_THRESHOLD:
            return "missed_upside", "hold-like action was followed by strong upside"
        if return_20d < AVOIDED_LOSS_RETURN_20D_THRESHOLD:
            return "avoided_loss", "hold-like action avoided a later decline"
        return "neutral_hold", "hold-like action was followed by limited movement"
    if action_group == "reduce_like":
        if return_20d < AVOIDED_LOSS_RETURN_20D_THRESHOLD:
            return "avoided_loss", "reduce-like action avoided a later decline"
        if return_20d > MISSED_UPSIDE_RETURN_20D_THRESHOLD:
            return "sold_too_early", "reduce-like action was followed by strong upside"
        return "neutral_reduce", "reduce-like action was followed by limited movement"
    return "pending", "action group is unknown"


def is_missed_ai_add_opportunity(item: TradeDecisionOutcomeItem) -> bool:
    return (
        item.ai_position_stance == "underweight"
        and item.ai_recommended_action_bias in {"allow_add", "prefer_pullback_add"}
        and item.action_group == "hold_like"
        and item.return_20d is not None
        and item.return_20d > MISSED_UPSIDE_RETURN_20D_THRESHOLD
    )


def is_calibrated_action_success(item: TradeDecisionOutcomeItem) -> bool:
    return (
        (item.draft_action in {"add_small", "add_on_pullback"} or item.final_action in {"add_small", "add_on_pullback"})
        and item.ai_position_stance == "underweight"
        and ((item.return_5d is not None and item.return_5d > 0) or (item.return_20d is not None and item.return_20d > 0))
    )


def is_risk_gate_avoided_loss(item: TradeDecisionOutcomeItem) -> bool:
    return (
        item.draft_action in ADD_LIKE_ACTIONS
        and item.action_group == "hold_like"
        and item.return_20d is not None
        and item.return_20d < 0
    )


def is_risk_gate_missed_upside(item: TradeDecisionOutcomeItem) -> bool:
    return (
        item.draft_action in ADD_LIKE_ACTIONS
        and item.action_group == "hold_like"
        and item.return_20d is not None
        and item.return_20d > MISSED_UPSIDE_RETURN_20D_THRESHOLD
    )


def _normalize_symbol_for_price(symbol: str) -> str:
    try:
        return normalize_longbridge_symbol(symbol)
    except ValueError:
        return str(symbol or "").strip().upper()


def _normalize_horizons(horizons: list[int] | None) -> list[int]:
    values = horizons or list(DEFAULT_HORIZONS)
    normalized = sorted({int(item) for item in values if int(item) > 0})
    return normalized or list(DEFAULT_HORIZONS)


def _decision_date(value: str) -> date | None:
    if not value:
        return None
    raw = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _parse_date(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def _return_pct(base: float | None, value: float | None) -> float | None:
    if base is None or base <= 0 or value is None:
        return None
    return round((value / base) - 1.0, 6)


def _avg_return(items: list[TradeDecisionOutcomeItem], field: str) -> float | None:
    values = [getattr(item, field) for item in items if getattr(item, field) is not None]
    return round(sum(values) / len(values), 6) if values else None


def _win_rate(items: list[TradeDecisionOutcomeItem], field: str) -> float:
    values = [getattr(item, field) for item in items if getattr(item, field) is not None]
    if not values:
        return 0.0
    return round(sum(1 for value in values if value > 0) / len(values), 4)


def _top_items(counter: Counter[str], limit: int = 20) -> list[dict]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def _top_decisions(items: list[TradeDecisionOutcomeItem], *, labels: set[str], reverse: bool) -> list[TradeDecisionOutcomeItem]:
    filtered = [item for item in items if item.outcome_label in labels and item.return_20d is not None]
    return sorted(filtered, key=lambda item: item.return_20d or 0.0, reverse=reverse)[:5]


def _label_value(label: str) -> int | None:
    if label in {"good_action", "avoided_loss"}:
        return 1
    if label in {"bad_add", "missed_upside", "sold_too_early"}:
        return -1
    if label.startswith("neutral_"):
        return 0
    return None


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
