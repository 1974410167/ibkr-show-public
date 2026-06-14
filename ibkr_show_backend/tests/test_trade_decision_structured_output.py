import json

from app.agents.trade_decision_cards import AccountFactSnapshot
from app.agents.trade_decision_structured_outputs import (
    build_debate_judge_contract,
    build_debate_rebuttal_contract,
    build_debate_thesis_contract,
    build_trade_plan_contract,
)
from app.services.trade_decision_sub_agents import (
    EVENT_CATALYST_SYSTEM_PROMPT,
    FUNDAMENTAL_VALUATION_SYSTEM_PROMPT,
    MARKET_TREND_SYSTEM_PROMPT,
    EventCatalystSubAgent,
    FundamentalValuationSubAgent,
    MarketTrendSubAgent,
)


class FakeLLM:
    def __init__(self, repairs: list[str] | None = None) -> None:
        self.repairs = list(repairs or [])
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return self.repairs.pop(0) if self.repairs else "not json"


class FakeAdapter:
    def __init__(self) -> None:
        self.client = type("Client", (), {"enabled": True})()

    def get_tool_catalog(self):
        return {}

    def call(self, tool_name, arguments):
        return {"ok": True, "tool": tool_name, "data": {}, "tool_call": {"tool_name": tool_name, "success": True}}


class FakeRuntime:
    def __init__(self, content: str, trace: list[dict] | None = None) -> None:
        self.content = content
        self.trace = trace if trace is not None else base_runtime_trace()

    def run(self, **kwargs):
        return {"content": self.content, "trace": list(self.trace)}


def patch_runtime(subagent, content: str, trace: list[dict] | None = None):
    subagent._build_runtime = lambda prompt_metadata=None: FakeRuntime(content, trace)  # noqa: SLF001
    return subagent


def snapshot(symbol: str = "AMD.US") -> AccountFactSnapshot:
    return AccountFactSnapshot(
        decision_type="entry_decision",
        symbol=symbol,
        normalized_symbol=symbol,
        user_question="test",
        net_liquidation=100000,
        cash=30000,
        deployable_liquidity=30000,
        deployable_liquidity_ratio=0.3,
        total_position_value=70000,
        top_positions=[],
        position_concentration=None,
        risk_concentration=None,
        margin_info=None,
        is_holding=False,
        quantity=None,
        avg_cost=None,
        current_price=100,
        market_value=None,
        position_pct=None,
        unrealized_pnl=None,
        unrealized_pnl_pct=None,
        realized_pnl=None,
        recent_trades=[],
        first_buy_date=None,
        last_trade_date=None,
        holding_days=None,
        latest_review=None,
        global_mistake_tags=[],
        data_quality={},
    )


def base_runtime_trace() -> list[dict]:
    return [
        {"event": "llm_start"},
        {
            "event": "tool_finish",
            "tool": "quote",
            "ok": True,
            "output": {
                "data": {"price": 100, "market_cap": 1000000000},
                "tool_call": {"tool_name": "quote", "success": True, "empty_result": False, "missing_fields": [], "parsed_fields": ["price"]},
            },
        },
        {
            "event": "tool_finish",
            "tool": "valuation",
            "ok": True,
            "output": {
                "data": {"pe_ttm": 28.5, "forward_pe": 22.0, "market_cap": 1000000000},
                "tool_call": {"tool_name": "valuation", "success": True, "empty_result": False, "missing_fields": [], "parsed_fields": ["pe_ttm"]},
            },
        },
        {
            "event": "tool_finish",
            "tool": "news_search",
            "ok": True,
            "output": {
                "data": {"items": [{"title": "news", "published_at": "2026-05-01", "source": "source", "summary": "summary"}]},
                "tool_call": {"tool_name": "news_search", "success": True, "empty_result": False, "missing_fields": [], "parsed_fields": ["items"]},
            },
        },
        {
            "event": "tool_finish",
            "tool": "finance_calendar",
            "ok": True,
            "output": {
                "data": {"next_earnings_date": "2026-07-25"},
                "tool_call": {"tool_name": "finance_calendar", "success": True, "empty_result": False, "missing_fields": [], "parsed_fields": ["next_earnings_date"]},
            },
        },
    ]


def market_json(**overrides) -> str:
    payload = {
        "summary": "趋势改善",
        "price_trend": "bullish",
        "recent_return_pct": 6.2,
        "volatility_summary": "medium",
        "relative_to_benchmark": "强于 QQQ",
        "score": 12,
        "key_points": ["动能改善"],
        "risks": [],
        "data_limitations": [],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def fundamental_json(**overrides) -> str:
    payload = {
        "summary": "基本面稳健",
        "score": 26,
        "pe_ttm": 28.5,
        "forward_pe": 22.0,
        "market_cap": 1000000000,
        "revenue_growth_summary": "增长稳定",
        "profitability_summary": "盈利稳定",
        "valuation_summary": "估值合理",
        "key_points": [],
        "risks": [],
        "data_limitations": [],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def event_json(**overrides) -> str:
    payload = {
        "summary": "存在中等催化",
        "next_earnings_date": "2026-07-25",
        "recent_news_count": 2,
        "sentiment": "positive",
        "catalyst_strength": "moderate",
        "key_events": ["财报窗口"],
        "risk_events": [],
        "score": 4,
        "data_limitations": [],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_debate_and_trade_plan_contracts_include_examples() -> None:
    contracts = [
        build_debate_thesis_contract("bull_thesis"),
        build_debate_thesis_contract("bear_thesis"),
        build_debate_rebuttal_contract("bull_rebuttal"),
        build_debate_rebuttal_contract("bear_rebuttal"),
        build_debate_judge_contract(),
        build_trade_plan_contract(),
    ]

    for contract in contracts:
        assert contract.examples, contract.name
        assert all(isinstance(example, dict) for example in contract.examples)


def test_market_trend_normal_json_no_repair() -> None:
    subagent = patch_runtime(MarketTrendSubAgent(FakeLLM(), FakeAdapter()), market_json())
    card, trace = subagent.generate(snapshot())

    assert card.price_trend == "bullish"
    assert card.score == 12
    assert trace.structured_output["repaired"] is False
    assert trace.status == "completed"


def test_market_trend_non_json_repairs_without_fallback() -> None:
    subagent = patch_runtime(MarketTrendSubAgent(FakeLLM([market_json(price_trend="neutral", score=8)]), FakeAdapter()), "not json")
    card, trace = subagent.generate(snapshot())

    assert card.price_trend == "neutral"
    assert trace.status == "completed"
    assert trace.fallback_used is False
    assert trace.structured_output["repaired"] is True


def test_market_trend_repair_failure_uses_fallback_with_structured_error() -> None:
    subagent = patch_runtime(MarketTrendSubAgent(FakeLLM(["still not json"]), FakeAdapter()), "not json")
    card, trace = subagent.generate(snapshot())

    assert trace.status == "fallback"
    assert trace.fallback_used is True
    assert trace.structured_output["error_code"] in {"LLM_REPAIR_FAILED", "LLM_JSON_PARSE_FAILED"}
    assert card.card_type == "market_trend"


def test_fundamental_normal_json_populates_card() -> None:
    subagent = patch_runtime(FundamentalValuationSubAgent(FakeLLM(), FakeAdapter()), fundamental_json())
    card, trace = subagent.generate(snapshot())

    assert card.pe_ttm == 28.5
    assert card.forward_pe == 22.0
    assert card.score == 26
    assert trace.structured_output["schema_validation_passed"] is True


def test_fundamental_missing_optional_fields_still_valid_and_tool_fallback_fills() -> None:
    subagent = patch_runtime(FundamentalValuationSubAgent(FakeLLM(), FakeAdapter()), fundamental_json(pe_ttm=None, forward_pe=None, market_cap=None))
    card, trace = subagent.generate(snapshot())

    assert trace.status == "completed"
    assert card.pe_ttm == 28.5
    assert card.forward_pe == 22.0
    assert card.market_cap == 1000000000


def test_fundamental_non_json_repair_failure_uses_deterministic_card() -> None:
    subagent = patch_runtime(FundamentalValuationSubAgent(FakeLLM(["bad repair"]), FakeAdapter()), "bad")
    card, trace = subagent.generate(snapshot())

    assert trace.status == "fallback"
    assert "确定性降级" in "".join(card.data_limitations)
    assert card.card_type == "fundamental_valuation"


def test_event_normal_json_populates_card() -> None:
    subagent = patch_runtime(EventCatalystSubAgent(FakeLLM(), FakeAdapter()), event_json())
    card, trace = subagent.generate(snapshot())

    assert card.recent_news_count == 2
    assert card.sentiment == "positive"
    assert card.key_events == ["财报窗口"]
    assert trace.status == "completed"


def test_event_schema_error_repairs_successfully() -> None:
    subagent = patch_runtime(
        EventCatalystSubAgent(FakeLLM([event_json(sentiment="neutral", catalyst_strength="weak", score=2)]), FakeAdapter()),
        event_json(sentiment="mixed"),
    )
    card, trace = subagent.generate(snapshot())

    assert card.sentiment == "neutral"
    assert trace.structured_output["repaired"] is True


def test_event_repair_failure_uses_deterministic_card() -> None:
    subagent = patch_runtime(EventCatalystSubAgent(FakeLLM(["bad repair"]), FakeAdapter()), "bad")
    card, trace = subagent.generate(snapshot())

    assert trace.status == "fallback"
    assert card.catalyst_strength == "weak"
    assert "事件催化 LLM 输出无法解析" in card.summary


def test_trade_decision_prompts_include_schema_examples_and_format_rules() -> None:
    for prompt in [MARKET_TREND_SYSTEM_PROMPT, FUNDAMENTAL_VALUATION_SYSTEM_PROMPT, EVENT_CATALYST_SYSTEM_PROMPT]:
        assert "JSON schema" in prompt
        assert "正常样例" in prompt
        assert "数据不足样例" in prompt or "亏损或数据不足样例" in prompt
        assert "不要 Markdown" in prompt
        assert "不要省略字段" in prompt


def test_trade_decision_mcp_subagents_inherit_llm_provider_output_limit() -> None:
    for subagent_cls in [MarketTrendSubAgent, FundamentalValuationSubAgent, EventCatalystSubAgent]:
        subagent = subagent_cls(FakeLLM(), FakeAdapter())
        runtime = subagent._build_runtime()  # noqa: SLF001

        assert subagent.max_tokens is None
        assert runtime.max_tokens is None
