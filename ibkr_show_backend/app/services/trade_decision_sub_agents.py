"""
Trade Decision Sub-Agents - bounded ReAct using ToolCallingRuntime.

Each MCP sub-agent:
- Has its own tools (via LongbridgeMCPToolAdapter)
- Uses ToolCallingRuntime with bounded max_rounds
- initial_tool_calls execute first, LLM decides whether to continue
- Outputs card JSON parsed into the correct dataclass
- Falls back gracefully on parse/validate errors or MCP unavailability

AccountFitSubAgent and RiskRewardSubAgent do NOT use MCP.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.agents.prompt_runtime import resolve_runtime_prompt
from app.agents.structured_output import StructuredOutputContract, StructuredOutputRuntime
from app.agents.trade_decision_structured_outputs import (
    build_event_catalyst_contract,
    build_fundamental_valuation_contract,
    build_market_trend_contract,
    build_risk_reward_contract,
)

logger = logging.getLogger(__name__)

MARKET_TREND_SYSTEM_PROMPT = (
    "你是市场趋势分析子 Agent。你的任务是基于行情数据评估标的短期趋势，但短期趋势不等于长期投资价值。\n"
    "系统会先并行执行初始工具调用（quote、candlesticks），你可以在第二轮追加工具调用。\n"
    "趋势判断必须综合价格走势、成交量、相对 QQQ/SPY/SMH 表现、波动率和近期回撤；不要只看单日涨跌。\n"
    "如果数据不足、信号冲突或行情不可用，不要强行 bullish / bearish，应使用 neutral 并写入 data_limitations。\n"
    "不要输出买卖指令，只输出趋势证据、风险和分数。\n"
    "只能输出 JSON object，不要 Markdown，不要代码块，不要额外解释，不要省略字段。\n"
    "不确定时填 null / [] / data_limitations，不要编造。\n"
    "JSON schema:\n"
    '{"summary": "...", "price_trend": "bullish|neutral|bearish", "recent_return_pct": 0.0, '
    '"volatility_summary": "high|medium|low", "relative_to_benchmark": "...", '
    '"score": 0-15, "key_points": [], "risks": [], "data_limitations": []}\n'
    "score: 0-15, bullish趋势给12-15分, neutral给7-11分, bearish给1-6分\n"
    "data_limitations 填写数据不足或工具调用失败的原因。\n"
    '正常样例: {"summary":"价格站上短期均线且相对 QQQ/SPY/SMH 表现略强，但波动仍偏高。","price_trend":"bullish","recent_return_pct":6.2,"volatility_summary":"high","relative_to_benchmark":"近一个月相对 QQQ 和 SMH 略强，相对 SPY 明显更强。","score":12,"key_points":["近期价格动能改善","相对半导体基准表现偏强"],"risks":["短期波动较高"],"data_limitations":[]}\n'
    '数据不足样例: {"summary":"行情或 benchmark 数据不足，短期趋势信号不完整，暂按中性处理。","price_trend":"neutral","recent_return_pct":0.0,"volatility_summary":"medium","relative_to_benchmark":null,"score":7,"key_points":[],"risks":["缺少足够行情或基准数据，趋势判断置信度较低"],"data_limitations":["benchmark 数据缺失，无法确认相对强弱"]}'
)

FUNDAMENTAL_VALUATION_SYSTEM_PROMPT = (
    "你是基本面估值分析子 Agent。你的任务是综合财报、估值、同业比较评估公司质量。\n"
    "系统先执行 company、financial_report、valuation，你可以第二轮追加 industry_peers、institution_rating。\n"
    "分析时必须区分三个维度：公司质量、估值水平、增长预期。不要把其中一个维度当成全部结论。\n"
    "不要机械地认为低 PE 一定便宜、高 PE 一定昂贵；成长质量、周期位置、利润率、现金流和预期变化都可能影响估值解释。\n"
    "亏损公司、强周期公司或一次性项目影响较大的公司，pe_ttm / forward_pe 可能不适用，必须在 data_limitations 或 valuation_summary 中说明。\n"
    "pe_ttm 和 forward_pe 必须从工具结果提取；缺失时不要编造数字，要写入 data_limitations。\n"
    "不得编造财报数据、管理层指引或分析师评级。\n"
    "只能输出 JSON object，不要 Markdown，不要代码块，不要额外解释，不要省略字段。\n"
    "不确定时填 null / [] / data_limitations，不要编造。\n"
    'JSON schema:\n'
    '{"summary": "...", "company_name": "...", "pe_ttm": 33.43, "forward_pe": 25.0, '
    '"revenue_growth_summary": "...", "profitability_summary": "...", '
    '"valuation_summary": "...", "score": 0-35, "key_points": [], "risks": [], "data_limitations": []}\n'
    "score: 0-35, fundamental高质量给15-20分, valuation合理给10-15分, 差给0-9分\n"
    "pe_ttm < 20 给15分, 20-35 给10分, > 35 给5分（满分含valuation的15分）\n"
    "如果工具返回了 pe_ttm，你必须原样填入；若公司亏损或指标不适用，可以填 null 或负数并说明。\n"
    '正常样例: {"summary":"公司盈利能力稳定，估值处于成长股可接受区间，但仍需关注增长兑现。","company_name":"Example Corp","pe_ttm":28.5,"forward_pe":24.0,"market_cap":250000000000.0,"ps_ttm":8.2,"dividend_yield":0.0,"revenue_growth_summary":"收入保持双位数增长。","profitability_summary":"毛利率和经营利润率保持稳定。","valuation_summary":"PE 和 forward PE 反映成长预期，不宜简单视为便宜。","industry":"Semiconductors","business_segments":[{"name":"Data Center","share":"high"}],"institutional_rating":"buy","target_price":150.0,"peer_relative_note":"估值略高于同业，但增长预期也更高。","score":26,"key_points":["盈利质量较好"],"risks":["估值对增长放缓敏感"],"data_limitations":[]}\n'
    '亏损或数据不足样例: {"summary":"公司仍处亏损或利润波动期，传统 PE 指标不适用，应更多参考收入、现金流和业务进展。","company_name":null,"pe_ttm":null,"forward_pe":null,"market_cap":null,"ps_ttm":null,"dividend_yield":null,"revenue_growth_summary":null,"profitability_summary":"利润为负或波动较大。","valuation_summary":"PE / forward PE 不适用，不能机械判断贵便宜。","industry":null,"business_segments":null,"institutional_rating":null,"target_price":null,"peer_relative_note":null,"score":12,"key_points":[],"risks":["亏损公司估值置信度较低"],"data_limitations":["pe_ttm / forward_pe 缺失或不适用"]}'
)

EVENT_CATALYST_SYSTEM_PROMPT = (
    "你是事件催化分析子 Agent。你的任务是分析新闻、财报日历、机构评级中的催化剂。\n"
    "系统先执行多组 news_search、finance_calendar、institution_rating，你可以追加更多 news_search，但最后必须收敛输出。\n"
    "你必须区分真实催化剂和普通新闻噪音：财报日、评级变化、重大产品发布、监管事件、重大订单、宏观冲击等才可能构成较强催化。\n"
    "recent_news_count 只能来自工具结果，不要估算或编造。\n"
    "sentiment 不确定或新闻互相冲突时使用 neutral；不要把新闻标题情绪直接等同于投资结论。\n"
    "不要把新闻标题当作完整事实背景；如果新闻只有标题，没有摘要、来源、发布时间，要明确降低置信度。\n"
    "如果 TC 清仓、CEO 邮件泄露、管理层争议、监管等事件只有标题或缺少背景，必须写“背景信息不足，不能确认影响程度”，不要编造细节。\n"
    "输出中必须区分 key_events、risk_events；如存在新闻背景不足，应在 data_limitations 或 missing_context 表述。\n"
    "不要输出买卖指令，只输出催化剂强弱、风险事件和分数。\n"
    "只能输出 JSON object，不要 Markdown，不要代码块，不要额外解释，不要省略字段。\n"
    "不确定时填 null / [] / data_limitations，不要编造。\n"
    'JSON schema:\n'
    '{"summary": "...", "next_earnings_date": "...", "recent_news_count": 0, '
    '"sentiment": "positive|neutral|negative", "catalyst_strength": "strong|moderate|weak", '
    '"key_events": [], "risk_events": [], "score": 0-5, "data_limitations": []}\n'
    "score: positive情绪给4-5分, negative给1-3分, neutral给2-3分，满分5分\n"
    '正常样例: {"summary":"近期有财报窗口和机构评级变化，存在中等事件催化，但需结合实际结果验证。","next_earnings_date":"2026-07-25","recent_news_count":6,"sentiment":"positive","catalyst_strength":"moderate","key_events":["即将进入财报窗口","机构上调目标价"],"risk_events":["财报不及预期可能压制估值"],"score":4,"data_limitations":[]}\n'
    '数据不足样例: {"summary":"新闻和财报日历信息不足，无法确认强催化，暂按弱催化处理。","next_earnings_date":null,"recent_news_count":0,"sentiment":"neutral","catalyst_strength":"weak","key_events":[],"risk_events":[],"score":2,"data_limitations":["财经日历暂未返回下一次财报日期","部分新闻缺少摘要或发布时间"]}'
)

from app.agents.runtime import AgentTool, ToolCallingRuntime
from app.agents.trade_decision_cards import (
    AccountFactSnapshot,
    AccountFitCard,
    BaseTradeDecisionCard,
    CardStance,
    EventCatalystCard,
    FundamentalValuationCard,
    MarketTrendCard,
    RiskRewardCard,
    TradeDecisionCardPack,
    TradeDecisionSubAgentTrace,
    build_fallback_account_fit_card,
    build_fallback_event_card,
    build_fallback_fundamental_card,
    build_fallback_market_trend_card,
    build_fallback_risk_reward_card,
)
from app.services.llm_service import LLMService
from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter


# === Shared MCP Tool Definitions ===

def _normalize_mcp_input_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert MCP inputSchema into a conservative OpenAI function schema."""
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    required = schema.get("required")
    return {
        "type": "object",
        "properties": properties,
        "required": required if isinstance(required, list) else [],
        "additionalProperties": False,
    }

def _build_mcp_tools(adapter: LongbridgeMCPToolAdapter) -> list[AgentTool]:
    """Build the list of allowed MCP tools for the sub-agents."""
    tools = []

    def make_handler(tool_name: str):
        def handler(**kwargs) -> dict:
            return adapter.call(tool_name, kwargs)
        return handler

    # Read-only market data tools
    tool_schemas = {
        "quote": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "candlesticks": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "period": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "adjust_type": {"type": "string"},
            },
            "required": ["symbol", "period", "start", "end"],
            "additionalProperties": False,
        },
        "history_candlesticks": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "period": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "adjust_type": {"type": "string"},
            },
            "required": ["symbol", "period", "start", "end"],
            "additionalProperties": False,
        },
        "news_search": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "keyword": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "company": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "financial_report": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "kind": {"type": "string"},
                "period": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "valuation": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "industry_peers": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "institution_rating": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "consensus": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "forecast_eps": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "business_segments": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "static_info": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "finance_calendar": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "market_status": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
    }

    public_catalog_tools: set[str] = set()
    catalog_schemas: dict[str, dict] = {}
    try:
        catalog = adapter.get_tool_catalog()
        public_catalog_tools = set(catalog.get("public_market_readonly") or [])
        catalog_schemas = {
            str(item.get("name")): item.get("input_schema") or {}
            for item in catalog.get("tools") or []
            if isinstance(item, dict)
        }
    except Exception:
        public_catalog_tools = set()

    dynamic_schema = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "symbols": {"type": "array", "items": {"type": "string"}},
            "keyword": {"type": "string"},
            "market": {"type": "string"},
            "period": {"type": "string"},
            "start": {"type": "string"},
            "end": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "additionalProperties": False,
    }
    for tool_name in sorted(set(tool_schemas) | public_catalog_tools):
        schema = (
            tool_schemas.get(tool_name)
            or _normalize_mcp_input_schema(catalog_schemas.get(tool_name))
            or dynamic_schema
        )
        desc = {
            "quote": "Get real-time quote for a symbol",
            "candlesticks": "Get candlestick/OHLCV data for a symbol",
            "history_candlesticks": "Get historical candlestick data",
            "news_search": "Search news articles for a symbol or keyword",
            "company": "Get company profile and static info",
            "financial_report": "Get financial reports and metrics",
            "valuation": "Get valuation metrics (PE, PB, etc.)",
            "industry_peers": "Get industry peer comparisons",
            "institution_rating": "Get institutional ratings and target prices",
            "consensus": "Get analyst consensus and target estimates",
            "forecast_eps": "Get analyst forward EPS estimates",
            "business_segments": "Get business segment contribution data",
            "static_info": "Get static security/company info",
            "finance_calendar": "Get earnings/dividend calendar",
            "market_status": "Get market session status",
        }.get(tool_name, f"Longbridge MCP tool: {tool_name}")

        tools.append(AgentTool(
            name=tool_name,
            description=desc,
            parameters=schema,
            handler=make_handler(tool_name),
            include_output_in_trace=True,
        ))

    return tools


# === Helper: extract JSON from LLM content ===

def _extract_json(raw: str) -> dict | None:
    """Extract JSON object from LLM raw response."""
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _optional_positive_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


_PE_TTM_PATTERN = re.compile(r'"pe_ttm"\s*:\s*(-?[\d.]+)')


def _fallback_extract_pe_ttm(raw_content: str, parsed: dict[str, Any]) -> float | None:
    """Extract pe_ttm from raw LLM content when JSON parsing misses it.

    Returns the raw value including negative (for loss-making companies).
    """
    raw_pe = parsed.get("pe_ttm")
    if raw_pe is not None:
        try:
            val = float(raw_pe)
            if val != 0:
                return val
        except (TypeError, ValueError):
            pass
    match = _PE_TTM_PATTERN.search(raw_content)
    if match:
        try:
            val = float(match.group(1))
            if val != 0:
                return val
        except (ValueError, TypeError):
            pass
    return None


def _optional_float(value: Any) -> float | None:
    """Extract a float value, returning None only for None/empty, allowing negative."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_data_limitations_from_runtime(parsed: dict[str, Any], trace: list[dict]) -> list[str]:
    """Extract user-facing data limitations from LLM output and trace.

    Only includes high-level, user-readable limitations. Tool-level mcp_field_missing
    diagnostics are excluded — they belong in card.missing_fields / card.tool_calls.
    """
    limitations: list[str] = []
    parsed_limitations = parsed.get("data_limitations")
    if isinstance(parsed_limitations, list):
        for item in parsed_limitations:
            cleaned = _sanitize_user_limitation(str(item))
            if cleaned:
                limitations.append(cleaned)
    elif parsed_limitations:
        cleaned = _sanitize_user_limitation(str(parsed_limitations))
        if cleaned:
            limitations.append(cleaned)

    for event in trace:
        if event.get("event") not in {"tool_error", "tool_finish"}:
            continue
        if event.get("event") == "tool_finish" and event.get("ok") is not False:
            continue
        tool = event.get("tool") or "unknown_tool"
        summary = str(event.get("summary") or "tool failed")[:160]
        limitations.append(_friendly_tool_limitation(str(tool), summary))
    return list(dict.fromkeys(limitations))[:20]


def _sanitize_user_limitation(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    lowered = text.lower()
    if (
        "agent exceeded max_rounds" in lowered
        or "subagent_failed" in lowered
        or text.startswith("mcp_field_missing")
        or "traceback" in lowered
        or "runtimeerror" in lowered
        or "jsondecodeerror" in lowered
        or "llm_json" in lowered
        or "runtime constraint" in lowered
        or "laufzeitbeschränkung" in lowered
        or ("tool" in lowered and ("truncated" in lowered or "abgeschnitten" in lowered))
    ):
        return "公开市场数据不足，已基于可用信息做保守分析"
    if "1970-01-01" in text:
        return "部分新闻缺少发布时间，时效性判断置信度降低"
    return text[:200]


def _friendly_tool_limitation(tool: str, summary: str = "") -> str:
    if tool == "finance_calendar":
        return "财经日历暂未返回下一次财报日期，财报时间窗口暂不确定"
    if tool == "news_search":
        return "公开新闻数据不足，已基于可用新闻做保守分析"
    if tool == "institution_rating":
        return "机构评级数据不足，评级变化催化判断置信度降低"
    return "公开市场数据不足，已基于可用信息做保守分析"


def _successful_source_tools(trace: list[dict]) -> list[str]:
    return [
        e.get("tool")
        for e in trace
        if e.get("event") == "tool_finish" and e.get("ok") is True and e.get("tool")
    ]


def _tool_call_records_from_trace(trace: list[dict]) -> list[dict]:
    records: list[dict] = []
    for event in trace:
        if event.get("event") not in {"tool_finish", "tool_error"}:
            continue
        output = event.get("output")
        if isinstance(output, dict) and isinstance(output.get("tool_call"), dict):
            record = dict(output["tool_call"])
            record.setdefault("tool_name", event.get("tool"))
            record.setdefault("request_args", event.get("arguments") or {})
            record.setdefault("success", event.get("ok") is True)
            records.append(record)
        else:
            records.append({
                "tool_name": event.get("tool") or "unknown_tool",
                "request_args": event.get("arguments") or {},
                "success": event.get("ok") is True,
                "empty_result": False,
                "raw_response_summary": event.get("summary") or "",
                "error_type": None if event.get("ok") else "tool_error",
                "missing_fields": [],
                "parsed_fields": [],
            })
    return records


def _tool_data_from_trace(trace: list[dict], tool_name: str) -> dict:
    for event in trace:
        if event.get("event") != "tool_finish" or event.get("tool") != tool_name or event.get("ok") is not True:
            continue
        output = event.get("output")
        if isinstance(output, dict) and isinstance(output.get("data"), dict):
            return output["data"]
    return {}


def _news_items_from_trace(trace: list[dict]) -> list[dict]:
    items: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for event in trace:
        if event.get("event") != "tool_finish" or event.get("tool") != "news_search" or event.get("ok") is not True:
            continue
        output = event.get("output")
        data = output.get("data") if isinstance(output, dict) else None
        news_items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(news_items, list):
            continue
        for item in news_items:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("title") or ""), str(item.get("published_at") or ""), str(item.get("source") or ""))
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def _news_missing_context_fields(news_items: list[dict]) -> list[dict]:
    missing: list[dict] = []
    for index, item in enumerate(news_items[:10]):
        for field_name in ("published_at", "source", "summary"):
            if not item.get(field_name):
                missing.append(
                    {
                        "tool_name": "news_search",
                        "field_name": field_name,
                        "item_index": index,
                        "title": str(item.get("title") or "")[:120],
                        "error_type": "field_not_in_parsed_output",
                    }
                )
    return missing


def _missing_fields_from_trace(trace: list[dict], *, tool_names: set[str] | None = None) -> list[dict]:
    missing: list[dict] = []
    for record in _tool_call_records_from_trace(trace):
        if tool_names and record.get("tool_name") not in tool_names:
            continue
        for item in record.get("missing_fields") or []:
            if isinstance(item, dict):
                missing.append(item)
    return missing


def _extract_financial_reports_from_trace(trace: list[dict]) -> list[dict]:
    """Recover a list of quarterly financial reports from the trace.

    The MCP adapter compacts financial_report output to a single summary
    dict, so we look at both the raw `tool_call.parsed_fields` (if any)
    and the compacted `data` payload. The goal is to give the
    FundamentalChangeEngine as much structured series as possible without
    fabricating data.
    """
    reports: list[dict] = []
    for event in trace or []:
        if event.get("event") != "tool_finish" or event.get("tool") != "financial_report" or event.get("ok") is not True:
            continue
        output = event.get("output") or {}
        if not isinstance(output, dict):
            continue
        record = output.get("tool_call") or {}
        if not isinstance(record, dict):
            record = {}
        data = output.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        # 1) raw quarterly series in `tool_call.parsed_fields` or `data.items`
        for src in (record.get("parsed_fields") or [], data.get("items") or []):
            if isinstance(src, list):
                for item in src:
                    if isinstance(item, dict):
                        reports.append(item)
        # 2) compact summary: try to lift known fields into one report
        if data and not reports:
            synthetic: dict = {}
            for k in (
                "revenue", "total_revenue", "sales", "net_revenue",
                "gross_margin", "gross_margin_pct", "gross_margin_percent",
                "operating_margin", "op_margin", "operating_margin_pct",
                "operating_cash_flow", "cfo", "ocf", "cash_from_operations",
                "free_cash_flow", "fcf",
            ):
                if k in data and data[k] is not None:
                    synthetic[k] = data[k]
            if synthetic:
                reports.append(synthetic)
        # 3) last resort: if data has top-level numeric fields, capture them
        if not reports and data:
            for k, v in data.items():
                if isinstance(v, (int, float)) and k not in {"sample_points"}:
                    reports.append({k: v})
                    break
    return reports


def _format_tool_issue(record: dict, field_name: str | None) -> str:
    payload = {
        "tool_name": record.get("tool_name"),
        "request_args": record.get("request_args") or {},
        "field_name": field_name,
        "success": record.get("success"),
        "empty_result": record.get("empty_result"),
        "raw_response_summary": record.get("raw_response_summary"),
        "error_type": record.get("error_type"),
    }
    return "mcp_field_missing: " + json.dumps(payload, ensure_ascii=False, default=str)


def _missing_record(tool_name: str, field_name: str, trace: list[dict]) -> dict:
    for record in _tool_call_records_from_trace(trace):
        if record.get("tool_name") != tool_name:
            continue
        for item in record.get("missing_fields") or []:
            if isinstance(item, dict) and item.get("field_name") == field_name:
                return item
        return {
            "tool_name": tool_name,
            "request_args": record.get("request_args") or {},
            "field_name": field_name,
            "success": record.get("success"),
            "empty_result": record.get("empty_result"),
            "raw_response_summary": record.get("raw_response_summary"),
            "error_type": "field_not_in_parsed_output",
        }
    return {
        "tool_name": tool_name,
        "request_args": {},
        "field_name": field_name,
        "success": False,
        "empty_result": True,
        "raw_response_summary": "tool_not_called",
        "error_type": "tool_not_called",
    }


def _data_quality_from_trace(trace: list[dict]) -> dict:
    records = _tool_call_records_from_trace(trace)
    return {
        "tool_call_count": len(records),
        "tool_success_count": sum(1 for item in records if item.get("success") is True),
        "tool_empty_count": sum(1 for item in records if item.get("empty_result") is True),
        "missing_field_count": sum(len(item.get("missing_fields") or []) for item in records),
        "tools": [
            {
                "tool_name": item.get("tool_name"),
                "success": item.get("success"),
                "empty_result": item.get("empty_result"),
                "parsed_fields": item.get("parsed_fields") or [],
            }
            for item in records
        ],
    }


def _repair_json_with_llm(llm_service: LLMService, raw_content: str, schema_hint: str) -> dict | None:
    """Deprecated: repair is now handled by StructuredOutputRuntime via contract. Kept for reference."""
    try:
        repaired = llm_service.chat(
            [
                {"role": "system", "content": "你是 JSON 修复器。只输出严格 JSON object，不要输出解释。"},
                {
                    "role": "user",
                    "content": (
                        f"请把下面内容修复为符合 schema 的 JSON。\nSchema: {schema_hint}\n"
                        f"原始内容:\n{raw_content[:4000]}"
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=1200,
            response_format={"type": "json_object"},
        )
        return _extract_json(str(repaired))
    except Exception:
        return None


# === AccountFitSubAgent (no MCP) ===

class AccountFitSubAgent:
    """Deterministic account fit assessment. No MCP, no LLM required (LLM only for summary)."""

    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    def generate(self, snapshot: AccountFactSnapshot) -> tuple[AccountFitCard, TradeDecisionSubAgentTrace]:
        trace = TradeDecisionSubAgentTrace(sub_agent_name="account_fit", started_at=datetime_now())
        started = time.perf_counter()
        try:
            card = self._build_card(snapshot)
            trace.finished_at = datetime_now()
            trace.elapsed_ms = int((time.perf_counter() - started) * 1000)
            trace.status = "completed"
            return card, trace
        except Exception as exc:
            trace.finished_at = datetime_now()
            trace.elapsed_ms = int((time.perf_counter() - started) * 1000)
            trace.status = "fallback"
            trace.error = str(exc)[:200]
            trace.fallback_used = True
            trace.fallback_reason = str(exc)[:200]
            return build_fallback_account_fit_card(snapshot.symbol, snapshot.decision_type, str(exc)), trace

    def _build_card(self, snapshot: AccountFactSnapshot) -> AccountFitCard:
        deployable = snapshot.deployable_liquidity or 0
        net_liq = snapshot.net_liquidation or 1
        liquidity_ratio = snapshot.deployable_liquidity_ratio or (deployable / net_liq if net_liq else 0)
        current_pct = snapshot.position_pct or 0
        is_holding = snapshot.is_holding

        if liquidity_ratio > 0.3 and current_pct < 0.05:
            fit_level = "excellent"
            score = 20
        elif liquidity_ratio > 0.15 and current_pct < 0.1:
            fit_level = "good"
            score = 16
        elif liquidity_ratio > 0.05:
            fit_level = "fair"
            score = 10
        else:
            fit_level = "poor"
            score = 4

        warnings: list[str] = []
        mistake_flags: list[str] = []
        if snapshot.latest_review:
            tags = snapshot.latest_review.get("mistake_tags") or []
            for tag in tags:
                tag_str = str(tag).upper()
                if tag_str in {"CHASE_HIGH", "POSITION_TOO_LARGE", "PANIC_SELL"}:
                    warnings.append(f"历史复盘标记: {tag}")
                    mistake_flags.append(str(tag))
            review_score = snapshot.latest_review.get("overall_score") or 50
            if review_score < 40:
                warnings.append("该标的最近复盘得分较低，需谨慎")
                if fit_level == "excellent":
                    fit_level = "fair"

        if current_pct <= 0:
            size_label = "none"
            max_pct = 0.05
        elif current_pct < 0.01:
            size_label = "tiny"
            max_pct = 0.05
        elif current_pct < 0.03:
            size_label = "small"
            max_pct = 0.08
        elif current_pct < 0.06:
            size_label = "medium"
            max_pct = 0.10
        elif current_pct < 0.10:
            size_label = "large"
            max_pct = 0.05
        else:
            size_label = "concentrated"
            max_pct = 0.03

        suggested_cash: float | None = None
        if is_holding and current_pct > 0.01:
            suggested_cash = None
        elif deployable > 0:
            max_invest = max_pct * net_liq - current_pct * net_liq
            suggested_cash = max(0, min(max_invest, deployable * 0.5))

        summary = self._summarize_fit(snapshot, fit_level, score, warnings)

        stance_map = {"excellent": CardStance.BULLISH, "good": CardStance.BULLISH, "fair": CardStance.NEUTRAL, "poor": CardStance.BEARISH}
        return AccountFitCard(
            card_type="account_fit",
            symbol=snapshot.symbol,
            decision_type=snapshot.decision_type,
            summary=summary,
            score=score,
            max_score=20,
            stance=stance_map.get(fit_level, CardStance.NEUTRAL),
            account_fit_level=fit_level,
            deployable_liquidity=deployable,
            current_position_pct=current_pct,
            max_suggested_position_pct=max_pct,
            suggested_cash_amount=suggested_cash,
            position_size_label=size_label,
            review_warnings=warnings,
            historical_mistake_flags=mistake_flags,
            evidence_quality="high",
            source_tools=[],
            created_at=datetime_now(),
        )

    def _summarize_fit(self, snapshot: AccountFactSnapshot, fit_level: str, score: int, warnings: list[str]) -> str:
        try:
            prompt = f"""基于以下账户数据，生成一句账户适配结论（50字以内，中文）：
账户流动性比例: {(snapshot.deployable_liquidity_ratio or 0)*100:.1f}%
当前仓位: {(snapshot.position_pct or 0)*100:.2f}%
{'已有持仓' if snapshot.is_holding else '无持仓'}
持仓天数: {snapshot.holding_days or '无历史'}
复盘警告: {', '.join(warnings) if warnings else '无'}
适配等级: {fit_level}
结论:"""
            result = self.llm_service.chat([{"role": "user", "content": prompt}], temperature=0.0, max_tokens=100)
            return str(result).strip()[:200] if result else f"账户适配{fit_level}，流动性充足"
        except Exception:
            return f"账户适配{fit_level}，可用流动性{(snapshot.deployable_liquidity_ratio or 0)*100:.1f}%，{'已有持仓' if snapshot.is_holding else '无持仓'}"


# === Base MCP Sub-Agent ===

class MCPSubAgent:
    """Base class for MCP sub-agents using bounded ReAct."""

    def __init__(
        self,
        llm_service: LLMService,
        adapter: LongbridgeMCPToolAdapter | None,
        max_rounds: int,
        max_tokens: int | None = None,
        prompt_service=None,
        monitoring_service=None,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        self.llm_service = llm_service
        self.adapter = adapter
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self.prompt_service = prompt_service
        self.monitoring_service = monitoring_service
        self.run_id = run_id
        self.task_id = task_id
        self._last_prompt_metadata: dict | None = None
        self._last_structured_output_metadata: dict | None = None

    def _build_runtime(self, prompt_metadata: dict | None = None) -> ToolCallingRuntime:
        return ToolCallingRuntime(
            self.llm_service,
            max_rounds=self.max_rounds,
            max_parallel_tools=5,
            max_observation_chars=6000,
            max_tokens=self.max_tokens,
            agent_name="trade_decision",
            node_name=self._sub_agent_name(),
            prompt_metadata=prompt_metadata,
            run_id=self.run_id,
            task_id=self.task_id,
            monitoring_service=self.monitoring_service,
            call_type="sub_agent",
        )

    def _build_system_prompt(self) -> str:
        raise NotImplementedError

    def _get_initial_tool_calls(self, symbol: str) -> list[dict]:
        raise NotImplementedError

    def _get_allowed_tools(self) -> list[AgentTool]:
        return _build_mcp_tools(self.adapter)

    def _structured_contract(self) -> StructuredOutputContract:
        raise NotImplementedError

    def _parse_llm_output(self, raw_content: str, snapshot: AccountFactSnapshot, trace: list[dict]) -> dict[str, Any]:
        result = StructuredOutputRuntime(self.llm_service, default_temperature=0.0, default_max_tokens=self.max_tokens).parse_validate_repair(
            raw_content,
            self._structured_contract(),
            context=self._structured_context(snapshot, trace),
        )
        metadata = {
            **result.metadata,
            "errors": result.errors,
            "trace": result.trace,
            "initial_error_code": result.errors[0].get("error_code") if result.errors else None,
        }
        self._last_structured_output_metadata = metadata
        trace.append(self._structured_output_event(metadata, ok=result.ok))
        if not result.ok or result.payload is None:
            raise RuntimeError(f"{self._sub_agent_name()} structured_output_failed: {result.error_code} {result.error_message or ''}".strip())
        return result.payload

    def _structured_context(self, snapshot: AccountFactSnapshot, trace: list[dict]) -> dict[str, Any]:
        return {
            "symbol": snapshot.symbol,
            "decision_type": snapshot.decision_type,
            "snapshot": {
                "current_price": snapshot.current_price,
                "is_holding": snapshot.is_holding,
                "position_pct": snapshot.position_pct,
                "user_question": snapshot.user_question,
                "data_quality": snapshot.data_quality,
            },
            "successful_source_tools": _successful_source_tools(trace),
            "data_quality": _data_quality_from_trace(trace),
            "runtime_trace": [
                {
                    "event": item.get("event"),
                    "tool": item.get("tool"),
                    "ok": item.get("ok"),
                    "summary": item.get("summary"),
                    "latency_ms": item.get("latency_ms"),
                }
                for item in trace[-30:]
            ],
        }

    def _structured_output_event(self, metadata: dict[str, Any], *, ok: bool) -> dict[str, Any]:
        return {
            "event": "structured_output_result",
            "contract_name": metadata.get("contract_name"),
            "ok": ok,
            "repaired": metadata.get("repaired"),
            "repair_attempts": metadata.get("repair_attempts"),
            "fallback_used": metadata.get("fallback_used"),
            "error_code": metadata.get("error_code") or metadata.get("initial_error_code"),
            "schema_validation_passed": metadata.get("schema_validation_passed"),
            "raw_response_preview": metadata.get("raw_response_preview"),
        }

    def _parse_card(self, parsed: dict[str, Any], raw_content: str, snapshot: AccountFactSnapshot, trace: list[dict]) -> Any:
        """Parse LLM content into the appropriate card. Override per sub-agent."""
        raise NotImplementedError

    def _build_card_fallback(self, symbol: str, decision_type: str, reason: str) -> Any:
        raise NotImplementedError

    def _build_card_fallback_from_trace(self, snapshot: AccountFactSnapshot, reason: str, trace: list[dict]) -> Any:
        return self._build_card_fallback(snapshot.symbol, snapshot.decision_type, reason)

    def generate(self, snapshot: AccountFactSnapshot) -> tuple[Any, TradeDecisionSubAgentTrace]:
        trace = TradeDecisionSubAgentTrace(sub_agent_name=self._sub_agent_name(), started_at=datetime_now())
        started = time.perf_counter()
        tools_used: list[str] = []
        rounds_used = 0
        runtime_trace: list[dict] = []

        try:
            system_prompt = self._build_system_prompt()
            trace.prompt_metadata = self._last_prompt_metadata
            # MCP unavailable check first
            if self.adapter is None or not (self.adapter.client and self.adapter.client.enabled):
                raise RuntimeError("MCP client is not available")

            runtime = self._build_runtime(self._last_prompt_metadata)
            tools = self._get_allowed_tools()
            initial_calls = self._get_initial_tool_calls(snapshot.symbol)
            logger.info(
                "SubAgent %s: starting with %d initial tool calls for %s",
                self._sub_agent_name(), len(initial_calls), snapshot.symbol,
            )

            result = runtime.run(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": self._build_user_content(snapshot)},
                ],
                tools=tools,
                response_format={"type": "json_object"},
                initial_tool_calls=initial_calls,
            )

            raw_content = result.get("content", "")
            runtime_trace = result.get("trace", [])
            logger.info(
                "SubAgent %s: completed, content_len=%d, trace_events=%d",
                self._sub_agent_name(), len(raw_content), len(runtime_trace),
            )

            # Count rounds and tools from trace
            rounds_used = max(1, sum(1 for e in runtime_trace if e.get("event") == "llm_start"))
            tools_used = [e.get("tool") for e in runtime_trace if e.get("event") in ("tool_start", "tool_finish") and e.get("tool")]
            tool_call_records = _tool_call_records_from_trace(runtime_trace)

            # Parse card
            parsed = self._parse_llm_output(raw_content, snapshot, runtime_trace)
            card = self._parse_card(parsed, raw_content, snapshot, runtime_trace)
            if not _successful_source_tools(runtime_trace):
                trace.status = "fallback"
                trace.fallback_used = True
                trace.fallback_reason = "public market tools returned no usable data"
            else:
                trace.status = "completed"
            trace.rounds_used = rounds_used
            trace.tools_called = list(dict.fromkeys(tools_used))
            trace.tool_call_count = len(tool_call_records)
            trace.tool_calls = tool_call_records
            trace.runtime_trace = runtime_trace
            trace.structured_output = self._last_structured_output_metadata
            return card, trace

        except Exception as exc:
            logger.warning("SubAgent %s failed: %s", self._sub_agent_name(), exc, exc_info=True)
            if runtime_trace:
                rounds_used = max(1, sum(1 for e in runtime_trace if e.get("event") == "llm_start"))
                tools_used = [e.get("tool") for e in runtime_trace if e.get("event") in ("tool_start", "tool_finish") and e.get("tool")]
                tool_call_records = _tool_call_records_from_trace(runtime_trace)
                trace.rounds_used = rounds_used
                trace.tools_called = list(dict.fromkeys(tools_used))
                trace.tool_call_count = len(tool_call_records)
                trace.tool_calls = tool_call_records
                trace.runtime_trace = runtime_trace
            if self._last_structured_output_metadata:
                trace.structured_output = self._last_structured_output_metadata
            trace.error = str(exc)[:200]
            trace.fallback_used = True
            trace.fallback_reason = str(exc)[:200]
            trace.status = "fallback"
            trace.prompt_metadata = self._last_prompt_metadata
            return self._build_card_fallback_from_trace(snapshot, str(exc), runtime_trace), trace
        finally:
            trace.finished_at = datetime_now()
            trace.elapsed_ms = int((time.perf_counter() - started) * 1000)

    def _sub_agent_name(self) -> str:
        raise NotImplementedError

    def _build_user_content(self, snapshot: AccountFactSnapshot) -> str:
        raise NotImplementedError


# === MarketTrendSubAgent ===

class MarketTrendSubAgent(MCPSubAgent):
    """Bounded ReAct (max_rounds=3) for market trend analysis via MCP."""

    def __init__(self, llm_service: LLMService, adapter: LongbridgeMCPToolAdapter | None, prompt_service=None, monitoring_service=None, run_id: str | None = None, task_id: str | None = None) -> None:
        super().__init__(llm_service, adapter, max_rounds=3, prompt_service=prompt_service, monitoring_service=monitoring_service, run_id=run_id, task_id=task_id)

    def _sub_agent_name(self) -> str:
        return "market_trend"

    def _build_system_prompt(self) -> str:
        prompt, metadata = resolve_runtime_prompt(self.prompt_service, "trade_decision_market_trend", MARKET_TREND_SYSTEM_PROMPT)
        self._last_prompt_metadata = metadata
        return prompt

    def _structured_contract(self) -> StructuredOutputContract:
        return build_market_trend_contract()

    def _build_user_content(self, snapshot: AccountFactSnapshot) -> str:
        return (
            f"标的: {snapshot.symbol}\n"
            f"决策类型: {snapshot.decision_type}\n"
            f"用户问题: {snapshot.user_question or '无'}\n"
            f"当前持仓: {'是' if snapshot.is_holding else '否'}，价格: {snapshot.current_price}\n"
            f"已有行情数据在下方工具结果中。请分析趋势并输出 JSON。"
        )

    def _get_initial_tool_calls(self, symbol: str) -> list[dict]:
        return [
            {"name": "quote", "arguments": {"symbol": symbol}},
            {"name": "candlesticks", "arguments": {"symbol": symbol, "period": "day", "start": _days_ago(260), "end": _days_ago(0), "adjust_type": "forward"}},
            {"name": "candlesticks", "arguments": {"symbol": "QQQ.US", "period": "day", "start": _days_ago(260), "end": _days_ago(0), "adjust_type": "forward"}},
            {"name": "candlesticks", "arguments": {"symbol": "SPY.US", "period": "day", "start": _days_ago(260), "end": _days_ago(0), "adjust_type": "forward"}},
            {"name": "candlesticks", "arguments": {"symbol": "SMH.US", "period": "day", "start": _days_ago(260), "end": _days_ago(0), "adjust_type": "forward"}},
        ]

    def _parse_card(self, parsed: dict[str, Any] | str, raw_content: str | AccountFactSnapshot, snapshot: AccountFactSnapshot | list[dict], trace: list[dict] | None = None) -> MarketTrendCard:
        if trace is None:
            raw_text = str(parsed)
            actual_snapshot = raw_content
            actual_trace = snapshot
            if not isinstance(actual_snapshot, AccountFactSnapshot) or not isinstance(actual_trace, list):
                raise TypeError("invalid legacy _parse_card arguments")
            parsed = self._parse_llm_output(raw_text, actual_snapshot, actual_trace)
            raw_content = raw_text
            snapshot = actual_snapshot
            trace = actual_trace
        assert isinstance(parsed, dict)
        assert isinstance(snapshot, AccountFactSnapshot)
        assert isinstance(trace, list)
        trend = str(parsed.get("price_trend", "neutral")).lower()
        score = float(parsed.get("score", 0))
        stance_map = {"bullish": CardStance.BULLISH, "neutral": CardStance.NEUTRAL, "bearish": CardStance.BEARISH}
        stance = stance_map.get(trend, CardStance.MIXED)
        limitations = _extract_data_limitations_from_runtime(parsed, trace)
        tool_calls = _tool_call_records_from_trace(trace)

        # Stage 02 - run TechnicalSignalEngine on raw candlesticks from the
        # trace and populate the card's technical signals. The LLM trend text
        # is used only as a label; the engine's numeric outputs are the
        # authoritative inputs to the Risk Gate.
        try:
            from app.services.technical_signal_engine import (
                TechnicalSignalEngine,
                extract_benchmark_candles_from_trace,
                extract_raw_candles_from_trace,
            )

            engine = TechnicalSignalEngine()
            symbol_candles = extract_raw_candles_from_trace(
                trace, "candlesticks", symbol=snapshot.symbol,
            )
            benchmark_candles = extract_benchmark_candles_from_trace(
                trace, ["QQQ.US", "SPY.US", "SMH.US"],
            )
            quote_data = _tool_data_from_trace(trace, "quote")
            quote = dict(quote_data) if isinstance(quote_data, dict) else {}
            technical_signals = engine.compute(
                symbol_candles=symbol_candles,
                benchmark_candles=benchmark_candles,
                quote=quote,
            )
            technical_signals_dict = technical_signals.to_dict()
            # Surface data_limitations on the card so the eval / Risk Gate
            # can see them.
            if technical_signals.data_limitations:
                limitations = list(dict.fromkeys(limitations + technical_signals.data_limitations))[:20]
            # evidence_quality must NOT be elevated when the engine could
            # not compute any signals.
            successful = bool(_successful_source_tools(trace))
            if not symbol_candles:
                technical_quality_downgrade = True
            else:
                technical_quality_downgrade = False
        except Exception as engine_exc:
            technical_signals_dict = {
                "data_limitations": [f"technical_signal_engine_failed: {str(engine_exc)[:120]}"],
                "trend_break_level": "unknown",
                "trend_break_reasons": [],
            }
            technical_quality_downgrade = True
            successful = bool(_successful_source_tools(trace))
            limitations = list(dict.fromkeys(limitations + technical_signals_dict["data_limitations"]))[:20]

        if successful and not technical_quality_downgrade:
            base_quality = "medium"
            if score >= 10:
                base_quality = "high"
        else:
            base_quality = "low"

        return MarketTrendCard(
            card_type="market_trend",
            symbol=snapshot.symbol,
            decision_type=snapshot.decision_type,
            summary=str(parsed.get("summary", ""))[:300],
            score=min(max(score, 0), 15),
            max_score=15,
            stance=stance,
            price_trend=trend,
            relative_to_benchmark=parsed.get("relative_to_benchmark"),
            benchmark_symbols=["QQQ.US", "SPY.US", "SMH.US"],
            recent_return_pct=float(parsed.get("recent_return_pct", 0) or 0),
            volatility_summary=str(parsed.get("volatility_summary", "medium")),
            data_limitations=limitations,
            evidence_quality=base_quality,
            source_tools=_successful_source_tools(trace),
            tool_calls=tool_calls,
            data_quality=_data_quality_from_trace(trace),
            missing_fields=_missing_fields_from_trace(trace, tool_names={"quote", "candlesticks", "history_candlesticks"}),
            technical_signals=technical_signals_dict,
            trend_break_level=str(technical_signals_dict.get("trend_break_level") or "unknown"),
            support_levels=list(technical_signals_dict.get("support_levels") or []),
            resistance_levels=list(technical_signals_dict.get("resistance_levels") or []),
            relative_strength_score=technical_signals_dict.get("relative_strength_score"),
            created_at=datetime_now(),
        )

    def _build_card_fallback(self, symbol: str, decision_type: str, reason: str) -> MarketTrendCard:
        return build_fallback_market_trend_card(symbol, decision_type, reason)


# === FundamentalValuationSubAgent ===

class FundamentalValuationSubAgent(MCPSubAgent):
    """Bounded ReAct (max_rounds=3) for fundamentals and valuation via MCP."""

    def __init__(self, llm_service: LLMService, adapter: LongbridgeMCPToolAdapter | None, prompt_service=None, monitoring_service=None, run_id: str | None = None, task_id: str | None = None) -> None:
        super().__init__(llm_service, adapter, max_rounds=3, prompt_service=prompt_service, monitoring_service=monitoring_service, run_id=run_id, task_id=task_id)

    def _sub_agent_name(self) -> str:
        return "fundamental_valuation"

    def _build_system_prompt(self) -> str:
        prompt, metadata = resolve_runtime_prompt(
            self.prompt_service,
            "trade_decision_fundamental_valuation",
            FUNDAMENTAL_VALUATION_SYSTEM_PROMPT,
        )
        self._last_prompt_metadata = metadata
        return prompt

    def _structured_contract(self) -> StructuredOutputContract:
        return build_fundamental_valuation_contract()

    def _build_user_content(self, snapshot: AccountFactSnapshot) -> str:
        return (
            f"标的: {snapshot.symbol}\n"
            f"决策类型: {snapshot.decision_type}\n"
            f"用户问题: {snapshot.user_question or '无'}\n"
            f"当前持仓: {'是' if snapshot.is_holding else '否'}，当前价格: {snapshot.current_price}\n"
            "已有公司信息、财报、估值数据在下方工具结果中。请分析并输出 JSON。"
        )

    def _get_initial_tool_calls(self, symbol: str) -> list[dict]:
        return [
            {"name": "company", "arguments": {"symbol": symbol}},
            {"name": "static_info", "arguments": {"symbol": symbol}},
            {"name": "quote", "arguments": {"symbol": symbol}},
            {"name": "financial_report", "arguments": {"symbol": symbol, "kind": "ALL", "period": "qf", "count": 4}},
            {"name": "valuation", "arguments": {"symbol": symbol}},
            {"name": "business_segments", "arguments": {"symbol": symbol}},
            {"name": "industry_peers", "arguments": {"symbol": symbol, "limit": 8}},
            {"name": "institution_rating", "arguments": {"symbol": symbol}},
            {"name": "consensus", "arguments": {"symbol": symbol}},
            {"name": "forecast_eps", "arguments": {"symbol": symbol}},
        ]

    def _parse_card(self, parsed: dict[str, Any] | str, raw_content: str | AccountFactSnapshot, snapshot: AccountFactSnapshot | list[dict], trace: list[dict] | None = None) -> FundamentalValuationCard:
        if trace is None:
            raw_text = str(parsed)
            actual_snapshot = raw_content
            actual_trace = snapshot
            if not isinstance(actual_snapshot, AccountFactSnapshot) or not isinstance(actual_trace, list):
                raise TypeError("invalid legacy _parse_card arguments")
            try:
                parsed = self._parse_llm_output(raw_text, actual_snapshot, actual_trace)
            except Exception as exc:
                return _build_deterministic_fundamental_card(actual_snapshot, actual_trace, str(exc))
            raw_content = raw_text
            snapshot = actual_snapshot
            trace = actual_trace
        assert isinstance(parsed, dict)
        assert isinstance(snapshot, AccountFactSnapshot)
        assert isinstance(trace, list)
        score = float(parsed.get("score", 0))
        company_data = _tool_data_from_trace(trace, "company")
        static_info = _tool_data_from_trace(trace, "static_info")
        quote_data = _tool_data_from_trace(trace, "quote")
        valuation_data = _tool_data_from_trace(trace, "valuation")
        peers_data = _tool_data_from_trace(trace, "industry_peers")
        rating_data = _tool_data_from_trace(trace, "institution_rating")
        consensus_data = _tool_data_from_trace(trace, "consensus")
        estimates_data = _tool_data_from_trace(trace, "forecast_eps")
        segments_data = _tool_data_from_trace(trace, "business_segments")
        financial_data = _tool_data_from_trace(trace, "financial_report")
        current_price = (
            _optional_positive_float(snapshot.current_price)
            or _optional_positive_float(quote_data.get("price"))
        )
        pe_ttm = _fallback_extract_pe_ttm(raw_content, parsed)
        if pe_ttm is None:
            pe_ttm = _optional_positive_float(valuation_data.get("pe_ttm"))
        forward_pe = _optional_float(parsed.get("forward_pe"))
        if forward_pe is None:
            forward_pe = _optional_positive_float(valuation_data.get("forward_pe"))
        if forward_pe is None:
            eps_forward = (
                _optional_positive_float(estimates_data.get("eps_forward"))
                or _optional_positive_float(consensus_data.get("eps_forward"))
                or _optional_positive_float(static_info.get("eps_forward"))
            )
            if current_price and eps_forward:
                forward_pe = round(current_price / eps_forward, 2)
        market_cap = _optional_positive_float(parsed.get("market_cap"))
        if market_cap is None:
            market_cap = (
                _optional_positive_float(company_data.get("market_cap"))
                or _optional_positive_float(static_info.get("market_cap"))
                or _optional_positive_float(valuation_data.get("market_cap"))
            )
        if market_cap is None and current_price:
            total_shares = _optional_positive_float(static_info.get("total_shares"))
            if total_shares:
                market_cap = round(total_shares * current_price, 2)
        ps_ttm = _optional_positive_float(parsed.get("ps_ttm"))
        if ps_ttm is None:
            ps_ttm = _optional_positive_float(valuation_data.get("ps_ttm"))
        dividend_yield = _optional_positive_float(parsed.get("dividend_yield"))
        if dividend_yield is None:
            dividend_yield = _optional_positive_float(valuation_data.get("dividend_yield"))
        company_name = str(parsed.get("company_name") or company_data.get("name") or static_info.get("name") or "")
        industry = parsed.get("industry") or rating_data.get("industry") or company_data.get("industry") or static_info.get("industry") or company_data.get("sector") or static_info.get("sector")
        business_segments = parsed.get("business_segments") or segments_data.get("segments") or company_data.get("business_segments") or static_info.get("business_segments")
        institutional_rating = parsed.get("institutional_rating") or rating_data.get("consensus") or consensus_data.get("consensus")
        target_price = (
            _optional_positive_float(parsed.get("target_price"))
            or _optional_positive_float(rating_data.get("target_price"))
            or _optional_positive_float(consensus_data.get("target_price"))
        )
        peer_relative_note = str(parsed.get("peer_relative_note") or "")
        if not peer_relative_note and peers_data.get("peers"):
            peer_relative_note = f"同业样本 {len(peers_data.get('peers') or [])} 个"
        limitations = _extract_data_limitations_from_runtime(parsed, trace)

        # --- Loss-making company: PE/forward PE not applicable ---
        pe_is_negative = pe_ttm is not None and pe_ttm < 0
        fwd_pe_is_negative = forward_pe is not None and forward_pe < 0
        if pe_is_negative or fwd_pe_is_negative:
            limitations.append(
                "valuation_not_applicable: 公司仍处亏损期，PE / forward PE 为负，"
                "传统 PE 估值不适用；已改用收入增速、PS、目标价和风险收益评估。"
            )

        # --- Only add user-level limitations for truly missing data ---
        # Suppress if resolved through cross-tool fallback
        if pe_ttm is None and not fwd_pe_is_negative:
            limitations.append("PE TTM 缺失或无有效值，估值评分无法使用 PE")
        if forward_pe is None and not pe_is_negative:
            # Only flag forward_pe missing if not a loss-making company
            eps_available = (
                _optional_positive_float(estimates_data.get("eps_forward"))
                or _optional_positive_float(consensus_data.get("eps_forward"))
                or _optional_positive_float(static_info.get("eps_forward"))
            )
            if not eps_available:
                limitations.append("Forward PE 无法计算：缺少 EPS 预测数据")
        if market_cap is None:
            # Only flag if truly unresolvable
            total_shares = _optional_positive_float(static_info.get("total_shares"))
            if not (current_price and total_shares):
                limitations.append("市值数据缺失")
        if not industry:
            limitations.append("行业分类数据缺失")
        if not business_segments:
            limitations.append("业务分拆数据缺失")
        if not institutional_rating:
            limitations.append("机构评级共识缺失")
        if target_price is None:
            limitations.append("目标价数据缺失")
        if score <= 0:
            limitations.append("基本面估值子代理返回零分")
        limitations = list(dict.fromkeys(limitations))[:20]
        tool_calls = _tool_call_records_from_trace(trace)

        # Stage 04 - run FundamentalChangeEngine on the structured inputs
        # the sub-agent has already collected. The LLM-derived stance / score
        # remain the high-level signal; the engine provides the structured
        # change_signals / thesis_broken / fundamental_status that the Risk
        # Gate and the composer will use.
        try:
            from app.services.fundamental_change_engine import FundamentalChangeEngine
            from app.services.investment_thesis import get_thesis

            engine = FundamentalChangeEngine()
            thesis = None
            try:
                thesis = get_thesis(snapshot.symbol)
            except Exception:
                thesis = None
            change_result = engine.evaluate(
                financial_reports=_extract_financial_reports_from_trace(trace),
                valuation=dict(valuation_data) if isinstance(valuation_data, dict) else None,
                business_segments=business_segments,
                institution_rating=dict(rating_data) if isinstance(rating_data, dict) else None,
                forecast_eps=dict(estimates_data) if isinstance(estimates_data, dict) else None,
                investment_thesis=thesis,
            )
            fundamental_status = change_result.fundamental_status
            thesis_broken = change_result.thesis_broken
            change_signals = list(change_result.change_signals)
            positive_signals = list(change_result.positive_signals)
            negative_signals = list(change_result.negative_signals)
            revenue_growth_trend = change_result.revenue_growth_trend
            margin_trend = change_result.margin_trend
            cash_flow_trend = change_result.cash_flow_trend
            guidance_change = change_result.guidance_change
            segment_growth_notes = list(change_result.segment_growth_notes)
            fundamental_change_evidence = list(change_result.evidence)
            if change_result.data_limitations:
                # Don't pollute the user-facing list with engine internals;
                # only surface ones that indicate we have no structured
                # financial_report series.
                structural = [
                    dl for dl in change_result.data_limitations
                    if any(
                        token in dl
                        for token in ("revenue", "margin", "现金流", "guidance")
                    )
                ]
                if structural:
                    limitations = list(dict.fromkeys(
                        limitations + [f"fundamental_change_engine: {s}" for s in structural]
                    ))[:20]
        except Exception as engine_exc:
            # Engine failure must NOT silently leave the card in default
            # state; we mark the status unknown and surface the failure so
            # the Risk Gate can apply a conservative confidence cap.
            fundamental_status = "unknown"
            thesis_broken = False
            change_signals = []
            positive_signals = []
            negative_signals = []
            revenue_growth_trend = None
            margin_trend = None
            cash_flow_trend = None
            guidance_change = None
            segment_growth_notes = []
            fundamental_change_evidence = []
            limitations = list(dict.fromkeys(
                limitations + [f"fundamental_change_engine_failed: {str(engine_exc)[:120]}"]
            ))[:20]

        return FundamentalValuationCard(
            card_type="fundamental_valuation",
            symbol=snapshot.symbol,
            decision_type=snapshot.decision_type,
            summary=str(parsed.get("summary", ""))[:300],
            score=min(max(score, 0), 35),
            max_score=35,
            stance=CardStance.BULLISH if (pe_ttm and pe_ttm < 30) else CardStance.NEUTRAL if pe_ttm else CardStance.MIXED,
            company_name=company_name,
            market_cap=market_cap,
            pe_ttm=pe_ttm,
            forward_pe=forward_pe,
            ps_ttm=ps_ttm,
            dividend_yield=dividend_yield,
            revenue_growth_summary=str(parsed.get("revenue_growth_summary", "")),
            profitability_summary=str(parsed.get("profitability_summary", "")),
            valuation_summary=str(parsed.get("valuation_summary", "")),
            peer_relative_note=peer_relative_note,
            industry=str(industry) if industry else None,
            business_segments=business_segments,
            institutional_rating=str(institutional_rating) if institutional_rating else None,
            target_price=target_price,
            data_limitations=limitations,
            evidence_quality="low" if score <= 0 or not _successful_source_tools(trace) else "high" if parsed.get("revenue_growth_summary") else "medium",
            source_tools=_successful_source_tools(trace),
            tool_calls=tool_calls,
            data_quality=_data_quality_from_trace(trace),
            missing_fields=_missing_fields_from_trace(trace, tool_names={"quote", "company", "static_info", "financial_report", "valuation", "business_segments", "industry_peers", "institution_rating", "consensus", "forecast_eps"}),
            fundamental_status=fundamental_status,
            thesis_broken=thesis_broken,
            change_signals=change_signals,
            positive_signals=positive_signals,
            negative_signals=negative_signals,
            revenue_growth_trend=revenue_growth_trend,
            margin_trend=margin_trend,
            cash_flow_trend=cash_flow_trend,
            guidance_change=guidance_change,
            segment_growth_notes=segment_growth_notes,
            fundamental_change_evidence=fundamental_change_evidence,
            created_at=datetime_now(),
        )

    def _build_card_fallback(self, symbol: str, decision_type: str, reason: str) -> FundamentalValuationCard:
        return build_fallback_fundamental_card(symbol, decision_type, reason)

    def _build_card_fallback_from_trace(self, snapshot: AccountFactSnapshot, reason: str, trace: list[dict]) -> FundamentalValuationCard:
        if trace:
            return _build_deterministic_fundamental_card(snapshot, trace, reason)
        return self._build_card_fallback(snapshot.symbol, snapshot.decision_type, reason)


def _build_deterministic_fundamental_card(snapshot: AccountFactSnapshot, trace: list[dict], reason: str) -> FundamentalValuationCard:
    company_data = _tool_data_from_trace(trace, "company")
    static_info = _tool_data_from_trace(trace, "static_info")
    quote_data = _tool_data_from_trace(trace, "quote")
    valuation_data = _tool_data_from_trace(trace, "valuation")
    financial_data = _tool_data_from_trace(trace, "financial_report")
    rating_data = _tool_data_from_trace(trace, "institution_rating")
    consensus_data = _tool_data_from_trace(trace, "consensus")
    forecast_data = _tool_data_from_trace(trace, "forecast_eps")
    segments_data = _tool_data_from_trace(trace, "business_segments")
    current_price = _optional_positive_float(snapshot.current_price) or _optional_positive_float(quote_data.get("price"))
    pe_ttm = _optional_positive_float(valuation_data.get("pe_ttm"))
    eps_forward = (
        _optional_positive_float(forecast_data.get("eps_forward"))
        or _optional_positive_float(consensus_data.get("eps_forward"))
        or _optional_positive_float(static_info.get("eps_forward"))
    )
    forward_pe = round(current_price / eps_forward, 2) if current_price and eps_forward else None
    market_cap = (
        _optional_positive_float(company_data.get("market_cap"))
        or _optional_positive_float(static_info.get("market_cap"))
        or _optional_positive_float(valuation_data.get("market_cap"))
    )
    if market_cap is None and current_price:
        total_shares = _optional_positive_float(static_info.get("total_shares"))
        if total_shares:
            market_cap = round(total_shares * current_price, 2)
    industry = rating_data.get("industry") or company_data.get("industry") or static_info.get("industry")
    business_segments = segments_data.get("segments") or company_data.get("business_segments") or static_info.get("business_segments")
    limitations = _extract_data_limitations_from_runtime({"data_limitations": [reason]}, trace)
    limitations.append("基本面估值 LLM 输出无法解析，已使用确定性降级方案")
    if forward_pe is None:
        limitations.append("Forward PE 无法计算：缺少 EPS 预测或价格数据")
    if market_cap is None:
        total_shares = _optional_positive_float(static_info.get("total_shares"))
        if not (current_price and total_shares):
            limitations.append("市值数据缺失")
    if not industry:
        limitations.append("行业分类数据缺失")
    if not business_segments:
        limitations.append("业务分拆数据缺失")
    score = 0
    if financial_data:
        score += 10
    if pe_ttm or forward_pe:
        score += 8
    if rating_data.get("consensus") or business_segments:
        score += 5
    return FundamentalValuationCard(
        card_type="fundamental_valuation",
        symbol=snapshot.symbol,
        decision_type=snapshot.decision_type,
        summary="基本面估值 LLM 输出无法解析，已基于 MCP 财报、估值、评级和业务分拆工具生成保守摘要。",
        score=min(score, 23),
        max_score=35,
        stance=CardStance.NEUTRAL if score else CardStance.INSUFFICIENT_DATA,
        company_name=str(company_data.get("name") or static_info.get("name") or ""),
        market_cap=market_cap,
        pe_ttm=pe_ttm,
        forward_pe=forward_pe,
        ps_ttm=_optional_positive_float(valuation_data.get("ps_ttm")),
        dividend_yield=_optional_positive_float(static_info.get("dividend_yield") or valuation_data.get("dividend_yield")),
        revenue_growth_summary=f"最近财报收入 {financial_data.get('revenue')}，同比 {financial_data.get('revenue_yoy')}" if financial_data else "",
        profitability_summary=f"净利润 {financial_data.get('net_income')}，ROE {financial_data.get('roe')}" if financial_data else "",
        valuation_summary=f"PE TTM {pe_ttm}，Forward PE {forward_pe}" if pe_ttm or forward_pe else "",
        peer_relative_note="industry_peers 未返回可用同业样本" if _tool_data_from_trace(trace, "industry_peers").get("total_returned") == 0 else "",
        industry=str(industry) if industry else None,
        business_segments=business_segments,
        institutional_rating=str(rating_data.get("consensus")) if rating_data.get("consensus") else None,
        target_price=_optional_positive_float(rating_data.get("target_price")),
        data_limitations=list(dict.fromkeys(limitations))[:20],
        evidence_quality="medium" if score else "low",
        source_tools=_successful_source_tools(trace),
        tool_calls=_tool_call_records_from_trace(trace),
        data_quality=_data_quality_from_trace(trace),
        missing_fields=_missing_fields_from_trace(trace, tool_names={"quote", "company", "static_info", "financial_report", "valuation", "business_segments", "industry_peers", "institution_rating", "consensus", "forecast_eps"}),
        created_at=datetime_now(),
    )


# === EventCatalystSubAgent ===

class EventCatalystSubAgent(MCPSubAgent):
    """Bounded ReAct (max_rounds=4) for events and catalysts via MCP."""

    def __init__(self, llm_service: LLMService, adapter: LongbridgeMCPToolAdapter | None, prompt_service=None, monitoring_service=None, run_id: str | None = None, task_id: str | None = None) -> None:
        super().__init__(llm_service, adapter, max_rounds=4, prompt_service=prompt_service, monitoring_service=monitoring_service, run_id=run_id, task_id=task_id)

    def _sub_agent_name(self) -> str:
        return "event_catalyst"

    def _build_system_prompt(self) -> str:
        prompt, metadata = resolve_runtime_prompt(self.prompt_service, "trade_decision_event_catalyst", EVENT_CATALYST_SYSTEM_PROMPT)
        self._last_prompt_metadata = metadata
        return prompt

    def _structured_contract(self) -> StructuredOutputContract:
        return build_event_catalyst_contract()

    def _build_user_content(self, snapshot: AccountFactSnapshot) -> str:
        return (
            f"标的: {snapshot.symbol}\n"
            f"决策类型: {snapshot.decision_type}\n"
            f"用户问题: {snapshot.user_question or '无'}\n"
            "已有新闻、日历、评级数据在下方工具结果中。请分析事件催化并输出 JSON。"
        )

    def _get_initial_tool_calls(self, symbol: str) -> list[dict]:
        return [
            {"name": "news_search", "arguments": {"symbol": symbol, "limit": 15}},
            {"name": "news_search", "arguments": {"symbol": symbol, "keyword": f"{symbol} earnings 财报", "limit": 8}},
            {"name": "news_search", "arguments": {"symbol": symbol, "keyword": f"{symbol} CEO management leaked email controversy", "limit": 8}},
            {"name": "finance_calendar", "arguments": {"symbol": symbol}},
            {"name": "institution_rating", "arguments": {"symbol": symbol}},
        ]

    def _parse_card(self, parsed: dict[str, Any] | str, raw_content: str | AccountFactSnapshot, snapshot: AccountFactSnapshot | list[dict], trace: list[dict] | None = None) -> EventCatalystCard:
        if trace is None:
            raw_text = str(parsed)
            actual_snapshot = raw_content
            actual_trace = snapshot
            if not isinstance(actual_snapshot, AccountFactSnapshot) or not isinstance(actual_trace, list):
                raise TypeError("invalid legacy _parse_card arguments")
            try:
                parsed = self._parse_llm_output(raw_text, actual_snapshot, actual_trace)
            except Exception as exc:
                return _build_deterministic_event_card(actual_snapshot, actual_trace, str(exc))
            raw_content = raw_text
            snapshot = actual_snapshot
            trace = actual_trace
        assert isinstance(parsed, dict)
        assert isinstance(snapshot, AccountFactSnapshot)
        assert isinstance(trace, list)
        sentiment = str(parsed.get("sentiment", "neutral")).lower()
        score = float(parsed.get("score", 0))
        sentiment_map = {"positive": CardStance.BULLISH, "negative": CardStance.BEARISH, "neutral": CardStance.NEUTRAL}
        calendar_data = _tool_data_from_trace(trace, "finance_calendar")
        rating_data = _tool_data_from_trace(trace, "institution_rating")
        news_items = _news_items_from_trace(trace)

        key_events = parsed.get("key_events", [])
        if isinstance(key_events, list):
            key_events = [str(e)[:100] for e in key_events[:5]]
        else:
            key_events = []

        risk_events = parsed.get("risk_events", [])
        if isinstance(risk_events, list):
            risk_events = [str(e)[:100] for e in risk_events[:3]]
        else:
            risk_events = []
        limitations = _extract_data_limitations_from_runtime(parsed, trace)
        next_earnings_date = parsed.get("next_earnings_date") or calendar_data.get("next_earnings_date")
        if not next_earnings_date:
            limitations.append("财经日历暂未返回下一次财报日期，财报时间窗口暂不确定")
        if not rating_data.get("consensus"):
            limitations.append("机构评级数据不足，评级变化催化判断置信度降低")
        if news_items:
            missing_published = sum(1 for item in news_items if isinstance(item, dict) and not item.get("published_at"))
            missing_source = sum(1 for item in news_items if isinstance(item, dict) and not item.get("source"))
            missing_summary = sum(1 for item in news_items if isinstance(item, dict) and not item.get("summary"))
            if missing_published:
                limitations.append("部分新闻缺少发布时间，时效性判断置信度降低")
            if missing_source:
                limitations.append("部分新闻缺少来源，可信度判断置信度降低")
            if missing_summary:
                limitations.append("部分新闻缺少摘要或背景，不能确认影响程度")
        else:
            limitations.append("公开新闻数据不足，已基于可用新闻做保守分析")
        limitations = list(dict.fromkeys(limitations))[:20]
        tool_calls = _tool_call_records_from_trace(trace)

        return EventCatalystCard(
            card_type="event_catalyst",
            symbol=snapshot.symbol,
            decision_type=snapshot.decision_type,
            summary=str(parsed.get("summary", ""))[:300],
            score=min(max(score, 0), 5),
            max_score=5,
            stance=sentiment_map.get(sentiment, CardStance.NEUTRAL),
            next_earnings_date=next_earnings_date,
            recent_news_count=int(parsed.get("recent_news_count", 0) or len(news_items) or 0),
            key_events=key_events,
            sentiment=sentiment,
            catalyst_strength=str(parsed.get("catalyst_strength", "neutral")),
            risk_events=risk_events,
            data_limitations=limitations,
            evidence_quality="low" if limitations and not _successful_source_tools(trace) else "medium",
            source_tools=_successful_source_tools(trace),
            tool_calls=tool_calls,
            data_quality=_data_quality_from_trace(trace),
            missing_fields=_missing_fields_from_trace(trace, tool_names={"news_search", "finance_calendar", "institution_rating"}) + _news_missing_context_fields(news_items),
            created_at=datetime_now(),
        )

    def _build_card_fallback(self, symbol: str, decision_type: str, reason: str) -> EventCatalystCard:
        return build_fallback_event_card(symbol, decision_type, reason)

    def _build_card_fallback_from_trace(self, snapshot: AccountFactSnapshot, reason: str, trace: list[dict]) -> EventCatalystCard:
        if trace:
            return _build_deterministic_event_card(snapshot, trace, reason)
        return self._build_card_fallback(snapshot.symbol, snapshot.decision_type, reason)


def _build_deterministic_event_card(snapshot: AccountFactSnapshot, trace: list[dict], reason: str) -> EventCatalystCard:
    calendar_data = _tool_data_from_trace(trace, "finance_calendar")
    news_items = _news_items_from_trace(trace)
    key_events = []
    for item in news_items[:5]:
        if isinstance(item, dict):
            title = item.get("title") or "news item"
            published = item.get("published_at") or "发布时间未知"
            source = item.get("source") or "来源未知"
            key_events.append(f"{published} {source}: {title}"[:100])
    limitations = _extract_data_limitations_from_runtime({"data_limitations": [reason]}, trace)
    limitations.append("事件催化 LLM 输出无法解析，已基于可用新闻做保守分析")
    if any(isinstance(item, dict) and not item.get("published_at") for item in news_items):
        limitations.append("部分新闻缺少发布时间，时效性判断置信度降低")
    if not calendar_data.get("next_earnings_date"):
        limitations.append("财经日历暂未返回下一次财报日期，财报时间窗口暂不确定")
    return EventCatalystCard(
        card_type="event_catalyst",
        symbol=snapshot.symbol,
        decision_type=snapshot.decision_type,
        summary="事件催化 LLM 输出无法解析，已基于 MCP 工具结果生成保守摘要。",
        score=2 if news_items else 0,
        max_score=5,
        stance=CardStance.NEUTRAL if news_items else CardStance.INSUFFICIENT_DATA,
        next_earnings_date=calendar_data.get("next_earnings_date"),
        recent_news_count=len(news_items),
        key_events=key_events,
        sentiment="neutral",
        catalyst_strength="weak",
        risk_events=[],
        data_limitations=list(dict.fromkeys(limitations))[:20],
        evidence_quality="medium" if news_items else "low",
        source_tools=_successful_source_tools(trace),
        tool_calls=_tool_call_records_from_trace(trace),
        data_quality=_data_quality_from_trace(trace),
        missing_fields=_missing_fields_from_trace(trace, tool_names={"news_search", "finance_calendar", "institution_rating"}) + _news_missing_context_fields(news_items),
        created_at=datetime_now(),
    )


# === RiskRewardSubAgent (no MCP, LLM text enhancement only) ===

RISK_REWARD_LLM_SYSTEM_PROMPT = (
    "你是风险收益分析文案增强器。你只负责用中文解释风险和机会，不能改变核心数值。\n"
    "系统已经用规则计算好了 score、stance、upside_potential_pct、downside_risk_pct、reward_risk_ratio、max_position_pct、wait_for_pullback。\n"
    "你只能输出以下字段：summary、key_risks、key_opportunities、risk_assessment_reason、data_limitations。\n"
    "不要输出或覆盖 score、stance、upside_potential_pct、downside_risk_pct、reward_risk_ratio、max_position_pct、wait_for_pullback。\n"
    "不要输出买卖指令或仓位建议。\n"
    "只能输出严格 JSON object，不要 Markdown，不要代码块，不要额外解释。\n"
    "不确定时填 [] 或 data_limitations，不要编造。\n"
)


class RiskRewardSubAgent:
    """Legacy risk/reward assessment.

    Risk/reward is now derived from TradePlanAgent in the graph. This class is
    kept for historical tests and manual compatibility paths.
    """

    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    def generate(
        self,
        snapshot: AccountFactSnapshot,
        account_fit: AccountFitCard | None = None,
        market_trend: MarketTrendCard | None = None,
        fundamental: FundamentalValuationCard | None = None,
        event: EventCatalystCard | None = None,
    ) -> tuple[RiskRewardCard, TradeDecisionSubAgentTrace]:
        trace = TradeDecisionSubAgentTrace(sub_agent_name="risk_reward", started_at=datetime_now())
        started = time.perf_counter()
        try:
            base_card = self._build_card(snapshot, account_fit, market_trend, fundamental, event)
            card = self._enhance_with_llm(snapshot, base_card, account_fit, market_trend, fundamental, event, trace)
            trace.finished_at = datetime_now()
            trace.elapsed_ms = int((time.perf_counter() - started) * 1000)
            trace.status = "completed"
            return card, trace
        except Exception as exc:
            trace.finished_at = datetime_now()
            trace.elapsed_ms = int((time.perf_counter() - started) * 1000)
            trace.status = "fallback"
            trace.error = str(exc)[:200]
            trace.fallback_used = True
            trace.fallback_reason = str(exc)[:200]
            return build_fallback_risk_reward_card(snapshot.symbol, snapshot.decision_type, str(exc)), trace

    def _enhance_with_llm(
        self,
        snapshot: AccountFactSnapshot,
        base_card: RiskRewardCard,
        account_fit: AccountFitCard | None,
        market_trend: MarketTrendCard | None,
        fundamental: FundamentalValuationCard | None,
        event: EventCatalystCard | None,
        trace: TradeDecisionSubAgentTrace,
    ) -> RiskRewardCard:
        try:
            user_content = self._build_llm_prompt(snapshot, base_card, account_fit, market_trend, fundamental, event)
            messages = [
                {"role": "system", "content": RISK_REWARD_LLM_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]

            raw_response = str(self.llm_service.chat(
                messages,
                temperature=0.0,
                response_format={"type": "json_object"},
            ))

            contract = build_risk_reward_contract()
            so_runtime = StructuredOutputRuntime(self.llm_service, default_temperature=0.0)
            so_result = so_runtime.parse_validate_repair(raw_response, contract)

            trace.structured_output = so_result.metadata
            trace.rounds_used = 1

            if so_result.ok and so_result.payload is not None:
                llm_output = so_result.payload
                # summary is a free-form text field; the LLM is the
                # primary source. Keep the engine's value only when the
                # LLM did not produce one.
                if llm_output.get("summary"):
                    base_card.summary = llm_output["summary"]

                # key_risks / key_opportunities: MERGE the rule-engine
                # list with the LLM list. The engine's structural read
                # (MA200 distance, support, ATR, fundamental drawdown,
                # target_price) must NOT be overwritten by the LLM; the
                # LLM is allowed to APPEND additional entries. We
                # de-duplicate and cap at a reasonable length.
                engine_risks = list(base_card.key_risks or [])
                llm_risks = llm_output.get("key_risks") or []
                if isinstance(llm_risks, list):
                    merged_risks = list(dict.fromkeys(engine_risks + [str(r) for r in llm_risks]))
                    base_card.key_risks = [r for r in merged_risks if r][:10]

                engine_opps = list(base_card.key_opportunities or [])
                llm_opps = llm_output.get("key_opportunities") or []
                if isinstance(llm_opps, list):
                    merged_opps = list(dict.fromkeys(engine_opps + [str(o) for o in llm_opps]))
                    base_card.key_opportunities = [o for o in merged_opps if o][:10]

                # data_limitations: MERGE. The engine surfaces
                # structural limitations (missing MA200 / support / ATR
                # / fundamental); the LLM can append but never replace.
                engine_limits = list(base_card.data_limitations or [])
                llm_limits = llm_output.get("data_limitations") or []
                if isinstance(llm_limits, list):
                    merged_limits = list(dict.fromkeys(
                        engine_limits + [str(d) for d in llm_limits if d]
                    ))
                    base_card.data_limitations = [d for d in merged_limits if d][:20]

                # risk_assessment_reason: append the LLM text to the
                # engine's action_guidance tag, never replace it. The
                # engine tag is the authoritative seed; the LLM can
                # elaborate.
                engine_reason = base_card.risk_assessment_reason or ""
                llm_reason = llm_output.get("risk_assessment_reason")
                if llm_reason:
                    if engine_reason and "RiskRewardEngine" in engine_reason:
                        # Keep the engine seed first so the trace always
                        # carries the deterministic anchor.
                        base_card.risk_assessment_reason = (
                            f"{engine_reason} | LLM: {llm_reason}"
                        )
                    elif engine_reason:
                        base_card.risk_assessment_reason = (
                            f"LLM: {llm_reason} | {engine_reason}"
                        )
                    else:
                        base_card.risk_assessment_reason = str(llm_reason)
            else:
                trace.fallback_used = True
                trace.fallback_reason = f"risk_reward_llm_enhancement_failed: {so_result.error_code or 'unknown'}"
                logger.info("RiskReward LLM enhancement failed, using rule-based card: %s", so_result.error_code)
        except Exception as exc:
            trace.rounds_used = 1
            trace.fallback_used = True
            trace.fallback_reason = f"risk_reward_llm_enhancement_failed: {str(exc)[:150]}"
            logger.info("RiskReward LLM enhancement exception, using rule-based card: %s", exc)

        return base_card

    def _build_llm_prompt(
        self,
        snapshot: AccountFactSnapshot,
        base_card: RiskRewardCard,
        account_fit: AccountFitCard | None,
        market_trend: MarketTrendCard | None,
        fundamental: FundamentalValuationCard | None,
        event: EventCatalystCard | None,
    ) -> str:
        parts = [
            f"标的: {snapshot.symbol}",
            f"决策类型: {snapshot.decision_type}",
            f"当前价格: {snapshot.current_price}",
            f"规则计算结果: 上行 {base_card.upside_potential_pct}%，下行 {base_card.downside_risk_pct}%，风险收益比 {base_card.reward_risk_ratio}x",
            f"规则评分: {base_card.score}/{base_card.max_score}",
            f"规则立场: {getattr(base_card.stance, 'value', base_card.stance) or 'unknown'}",
        ]
        if account_fit:
            parts.append(f"账户适配: {account_fit.summary}")
        if market_trend:
            parts.append(f"市场趋势: {market_trend.summary}")
        if fundamental:
            parts.append(f"基本面估值: {fundamental.summary}")
        if event:
            parts.append(f"事件催化: {event.summary}")
        parts.append("请基于以上信息，输出风险收益分析的文案字段（summary、key_risks、key_opportunities、risk_assessment_reason、data_limitations）。")
        return "\n".join(parts)

    def _build_card(
        self,
        snapshot: AccountFactSnapshot,
        account_fit: AccountFitCard | None,
        market_trend: MarketTrendCard | None,
        fundamental: FundamentalValuationCard | None,
        event: EventCatalystCard | None,
    ) -> RiskRewardCard:
        # Stage 05 - use RiskRewardEngine. The old cost-basis / +30% algorithm
        # is intentionally NOT used here: it systematically underestimated
        # downside (avg_cost * 0.85) and over-promised upside (price * 1.3).
        technical_signals: dict | None = None
        if market_trend is not None and getattr(market_trend, "technical_signals", None):
            technical_signals = market_trend.technical_signals

        try:
            from app.services.investment_thesis import get_thesis
            from app.services.risk_reward_engine import RiskRewardEngine

            thesis = None
            try:
                thesis = get_thesis(snapshot.symbol)
            except Exception:
                thesis = None

            engine = RiskRewardEngine()
            estimate = engine.estimate(
                snapshot=snapshot,
                account_fit=account_fit,
                market_trend=market_trend,
                fundamental=fundamental,
                event=event,
                investment_thesis=thesis,
                technical_signals=technical_signals,
                last_close=snapshot.current_price,
            )
        except Exception:
            # Engine failure is non-fatal; fall back to a conservative empty
            # estimate so the LLM enhancement layer can still run.
            from app.services.risk_reward_engine import RiskRewardEstimate

            estimate = RiskRewardEstimate(
                upside_potential_pct=None,
                downside_risk_pct=None,
                reward_risk_ratio=None,
                max_position_pct=0.05,
                position_size_label="unknown",
                confidence="low",
                wait_for_pullback=True,
                data_limitations=["RiskRewardEngine unavailable, results not reliable"],
                action_guidance="wait",
            )

        ratio = estimate.reward_risk_ratio
        if ratio is None:
            score = 4
            stance = CardStance.INSUFFICIENT_DATA
        elif ratio >= 2.0:
            score = 14
            stance = CardStance.BULLISH
        elif ratio >= 1.5:
            score = 12
            stance = CardStance.BULLISH
        elif ratio >= 1.0:
            score = 8
            stance = CardStance.NEUTRAL
        else:
            score = 4
            stance = CardStance.BEARISH

        # Build a structured summary for the LLM enhancement layer.
        upside_disp = "n/a" if estimate.upside_potential_pct is None else f"{estimate.upside_potential_pct:.1f}%"
        downside_disp = "n/a" if estimate.downside_risk_pct is None else f"{estimate.downside_risk_pct:.1f}%"
        ratio_disp = "n/a" if ratio is None else f"{ratio:.2f}"
        summary = (
            f"上行 {upside_disp}，下行 {downside_disp}，风险收益比 {ratio_disp}x"
            f"（RiskRewardEngine 确定性估算，不依赖成本价）"
        )

        # The key_risks / key_opportunities are still LLM-enhanced later
        # but seed them with the engine's structural read so the card is
        # never empty.
        key_risks: list[str] = []
        if estimate.downside_scenarios:
            for s in estimate.downside_scenarios[:3]:
                scen = str(s.get("scenario") or "")
                dist = s.get("distance_pct")
                if dist is not None:
                    key_risks.append(f"{scen} 距离 {dist:.1f}%")
        if not key_risks and estimate.downside_risk_pct is not None:
            key_risks.append(f"下行风险 {estimate.downside_risk_pct:.1f}%")
        if not key_risks:
            key_risks.append("下行风险数据不足")

        key_opportunities: list[str] = []
        if estimate.upside_scenarios:
            for s in estimate.upside_scenarios[:3]:
                scen = str(s.get("scenario") or "")
                dist = s.get("distance_pct")
                if dist is not None:
                    key_opportunities.append(f"{scen} 距离 {dist:.1f}%")
        if not key_opportunities and estimate.upside_potential_pct is not None:
            key_opportunities.append(f"上行空间 {estimate.upside_potential_pct:.1f}%")
        if not key_opportunities:
            key_opportunities.append("上行空间数据不足")

        # Position size label from the engine (already capped by risk_class)
        position_size_label = estimate.position_size_label
        if position_size_label == "unknown" and account_fit is not None:
            position_size_label = account_fit.position_size_label

        return RiskRewardCard(
            card_type="risk_reward",
            symbol=snapshot.symbol,
            decision_type=snapshot.decision_type,
            summary=summary,
            score=score,
            max_score=15,
            stance=stance,
            upside_potential_pct=estimate.upside_potential_pct,
            downside_risk_pct=estimate.downside_risk_pct,
            reward_risk_ratio=estimate.reward_risk_ratio,
            max_position_pct=estimate.max_position_pct,
            wait_for_pullback=estimate.wait_for_pullback,
            wait_for_pullback_pct=estimate.wait_for_pullback_pct,
            pullback_entry_level=estimate.pullback_entry_level,
            action_guidance=estimate.action_guidance,
            position_size_label=position_size_label,
            key_risks=key_risks,
            key_opportunities=key_opportunities,
            evidence_quality=estimate.confidence if estimate.confidence in {"high", "medium", "low"} else "low",
            source_tools=[],
            data_limitations=list(estimate.data_limitations),
            risk_assessment_reason=f"RiskRewardEngine action_guidance={estimate.action_guidance}",
            downside_scenarios=list(estimate.downside_scenarios),
            upside_scenarios=list(estimate.upside_scenarios),
            stop_add_level=estimate.stop_add_level,
            invalidation_level=estimate.invalidation_level,
            trim_level=estimate.trim_level,
            risk_reward_confidence=estimate.confidence,
            risk_reward_thesis_broken=bool(fundamental and fundamental.thesis_broken),
            created_at=datetime_now(),
        )


# === TradeDecisionCardBuilder (Deprecated) ===

class TradeDecisionCardBuilder:
    """Deprecated. Use TradeDecisionGraphRunner instead.

    The old ThreadPoolExecutor DAG has been removed. This class is kept only
    for import compatibility. build_card_pack raises RuntimeError.
    """

    def __init__(self, *args, **kwargs) -> None:
        pass

    def build_card_pack(self, *args, **kwargs):
        raise RuntimeError(
            "TradeDecisionCardBuilder is deprecated. "
            "Use TradeDecisionGraphRunner (LangGraph) for trade decision orchestration."
        )


def datetime_now() -> str:
    return datetime.now(timezone.utc).isoformat()
