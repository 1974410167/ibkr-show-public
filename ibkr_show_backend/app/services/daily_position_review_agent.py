from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.agents.context_budget import enforce_section_budget
from app.agents.daily_review_evidence_cards import (
    DailyReviewEvidenceCardPack,
    compute_card_pack_summary,
)
from app.agents.evidence_schema import (
    build_daily_position_review_evidence_pack,
    build_daily_position_review_evidence_pack_from_cards,
)
from app.agents.evidence_summary import build_evidence_summary
from app.agents.invariants import normalize_daily_position_review_output
from app.agents.output_schemas import DailyPositionReviewOutput
from app.agents.prompt_runtime import resolve_runtime_prompt
from app.agents.runtime import AgentTool, ToolCallingRuntime
from app.agents.trace_summary import build_run_trace_summary
from app.agents.versions import (
    AGENT_MODE_FIXED_EVIDENCE_WITH_SINGLE_TOOL,
    DAILY_POSITION_REVIEW_AGENT_MODE_SUBAGENT_CARDS,
    DAILY_POSITION_REVIEW_AGENT_VERSION,
    DAILY_POSITION_REVIEW_EVIDENCE_BUILDER_VERSION,
    DAILY_POSITION_REVIEW_PROMPT_VERSION,
    DAILY_POSITION_REVIEW_TOOLSET_VERSION,
    OUTPUT_SCHEMA_VERSION,
    build_metadata,
)
from app.services.daily_position_review_repository import DailyPositionReviewRepository
from app.services.daily_position_review_service import DailyPositionReviewService
from app.services.daily_review_evidence_card_builder import DailyReviewEvidenceCardBuilder
from app.services.daily_review_related_asset_service import DailyReviewRelatedAssetService
from app.services.llm_service import (
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    DEFAULT_INPUT_TOKEN_LIMIT,
    DEFAULT_OUTPUT_TOKEN_LIMIT,
    LLMConfigError,
    LLMService,
)

SYSTEM_PROMPT = """你是每日持仓复盘 Agent。
你的任务是基于 IBKR 账户事实和 Longbridge 公开市场数据，生成每日持仓复盘：账户涨跌归因、个股异动解释、风险提示和明日观察清单。
账户、持仓、交易、成本、盈亏、现金等个人数据只能来自 IBKR。
Longbridge 只能作为公开市场、行情、新闻、财报、估值、宏观和行业数据源。
LLM 不负责计算收益、仓位、贡献率、浮盈亏等确定性数字；这些数字必须来自工具结果。
如果公开数据缺失，必须写入 data_limitations，不能编造原因。
账户归因优先于新闻叙事：先解释哪些持仓和仓位贡献影响账户，再用公开信息辅助解释原因。
区分确定事实、合理推断和无法确认的内容；不要把单日涨跌过度归因到单一新闻。
不要输出强买强卖指令，只输出观察条件。
最终必须输出严格 JSON object，不要输出 Markdown，不要代码块，不要额外解释，不要省略字段。"""

# Sub-agent card mode system prompt
SYSTEM_PROMPT_SUBAGENT_CARDS = """你是每日持仓复盘 Agent。
你的任务是基于 SymbolEvidenceCard、MacroEvidenceCard 和 IBKR 核心事实，生成每日持仓复盘：账户涨跌归因、个股异动解释、风险提示和明日观察清单。
账户、持仓、交易、成本、盈亏、现金等个人数据只能来自 IBKR。
Longbridge 只能作为公开市场、行情、新闻、财报、估值、宏观和行业数据源。
LLM 不负责计算收益、仓位、贡献率、浮盈亏等确定性数字；这些数字必须来自工具结果。
如果公开数据缺失，必须写入 data_limitations，不能编造原因。
不要输出强买强卖指令，只输出观察条件。
最终必须输出严格 JSON，不要输出 Markdown。

你已经收到了子 Agent 生成的证据卡片（SymbolEvidenceCard 和 MacroEvidenceCard）。
这些卡片是高密度证据，已由子 Agent 将公开解释材料摘要成结构化格式。
你的任务是基于这些卡片和 IBKR 核心事实，生成最终每日复盘报告。
不要重新计算 IBKR 数字，只基于卡片中的摘要进行解释和归因。

分析要求：
1. 账户归因优先于新闻叙事：先说明账户层面的主要贡献、拖累、仓位和风险变化，再引用卡片解释可能驱动因素。
2. 不要强行解释所有波动；如果卡片证据不足或公开数据缺失，要明确写入 data_limitations。
3. 区分确定事实、合理推断和无法确认；不要把单日涨跌过度归因到单一新闻或单一宏观事件。
4. 明日关注清单只能是观察条件，不是确定性买卖指令。
5. 最终必须输出严格 JSON object，不要输出 Markdown，不要代码块，不要额外解释，不要省略字段。

简短完整输出样例：
{
  "report_date": "2026-05-20",
  "summary": "今日账户小幅上涨，主要由 AMD 和 MSFT 贡献。",
  "account_conclusion": "账户收益来自大仓位贡献，公开新闻只作为辅助解释。",
  "attribution_summary": "主要贡献来自 AMD，主要拖累来自 INTC；具体盈亏和贡献率以 IBKR 确定性数据为准。",
  "major_contributors_analysis": [{"symbol": "AMD.US", "analysis": "仓位贡献为正，公开证据显示半导体板块偏强。"}],
  "major_drags_analysis": [{"symbol": "INTC.US", "analysis": "当日拖累账户表现，公开证据不足以确认单一原因。"}],
  "focus_symbol_analyses": [{"symbol": "AMD.US", "price_action": "跑赢 QQQ 和 SMH。", "account_impact": "对账户正贡献较高。", "possible_reasons": ["半导体板块偏强"], "valuation_note": "估值仍有成长溢价。", "cost_position_note": "成本和浮盈亏以 IBKR 数据为准。", "watch_points": ["观察 SMH 是否继续确认方向"], "data_limitations": []}],
  "market_context": "宏观信号 mixed，科技相对偏强。",
  "risk_analysis": "继续关注单一标的集中度和现金比例。",
  "tomorrow_watchlist": [{"symbol": "AMD.US", "reason": "大仓位且波动较高", "key_levels": [], "events": [], "conditions": ["观察是否继续跑赢 SMH"]}],
  "operation_observation": "仅作为复盘观察，不构成确定性买卖指令。",
  "data_limitations": [],
  "evidence_used": ["IBKR account snapshot", "SymbolEvidenceCard", "MacroEvidenceCard"]
}"""

MAX_LLM_REPAIR_ATTEMPTS = 3


class DailyPositionReviewAgentError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def extract_json_object(raw_response: str) -> dict:
    """Deprecated: use app.agents.structured_output.extract_json_object instead."""

    try:
        return json.loads(raw_response)
    except json.JSONDecodeError:
        pass

    text = raw_response.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise DailyPositionReviewAgentError("LLM_JSON_PARSE_FAILED", "LLM response is not valid JSON")


class DailyPositionReviewAgent:
    def __init__(
        self,
        review_service: DailyPositionReviewService,
        llm_service: LLMService,
        repository: DailyPositionReviewRepository,
        *,
        email_service=None,
        related_asset_service=None,
        longbridge_client=None,
        symbol_agent=None,
        macro_agent=None,
        prompt_service=None,
        trace_service=None,
        replay_service=None,
        monitoring_service=None,
    ) -> None:
        self.review_service = review_service
        self.llm_service = llm_service
        self.repository = repository
        self._email_service = email_service
        self._related_asset_service = related_asset_service
        self._longbridge_client = longbridge_client or getattr(review_service, "longbridge_client", None)
        self._symbol_agent = symbol_agent
        self._macro_agent = macro_agent
        self.prompt_service = prompt_service
        self.trace_service = trace_service
        self.replay_service = replay_service
        self._monitoring_service = monitoring_service
        self._graph_runner = None

    def _get_graph_runner(self):
        if self._graph_runner is None:
            from app.agents.daily_position_review_graph.runner import DailyPositionReviewGraphRunner
            self._graph_runner = DailyPositionReviewGraphRunner(
                review_service=self.review_service,
                llm_service=self.llm_service,
                repository=self.repository,
                email_service=self._email_service,
                related_asset_service=self._related_asset_service,
                longbridge_client=self._longbridge_client,
                symbol_agent=self._symbol_agent,
                macro_agent=self._macro_agent,
                prompt_service=self.prompt_service,
                trace_service=self.trace_service,
                replay_service=self.replay_service,
                monitoring_service=self._monitoring_service,
            )
        return self._graph_runner

    def health(self, longbridge_configured: bool) -> dict:
        llm_configured = self.llm_service.get_active_provider() is not None
        return {
            "enabled": True,
            "llm_configured": llm_configured,
            "longbridge_configured": longbridge_configured,
            "account_data_source": "IBKR_ONLY",
            "public_market_data_source": "LONGBRIDGE_PUBLIC_ONLY",
            "agent_mode": "daily_position_review_langgraph_v1",
            "graph_version": "daily_position_review_graph_v1",
            "message": "Daily position review agent is ready" if llm_configured else "LLM active provider is missing",
        }

    def generate_review(self, report_date: str, *, auto_email: bool = False, progress_reporter: Any = None) -> dict:
        """
        Generate a daily position review document via LangGraph runner.
        """
        if self.llm_service.get_active_provider() is None:
            raise LLMConfigError("No active LLM provider is configured")

        runner = self._get_graph_runner()
        if progress_reporter is not None:
            return runner.generate_review(report_date, auto_email=auto_email, progress_reporter=progress_reporter)
        return runner.generate_review(report_date, auto_email=auto_email)

    def _generate_review_subagent_cards(self, report_date: str) -> dict:
        """DEPRECATED: Use LangGraph runner via generate_review()."""
        raise RuntimeError("deprecated; use DailyPositionReviewGraphRunner via generate_review()")

    def _generate_review_legacy(self, report_date: str, fallback_reason: str | None = None) -> dict:
        """DEPRECATED: Use LangGraph runner instead. Kept for reference only."""
        raise RuntimeError("deprecated; use DailyPositionReviewGraphRunner via generate_review()")
        """
        Legacy single-tool mode - kept as fallback.
        This mode puts all public context + IBKR facts in one evidence pack,
        which can trigger context budget truncation.
        """
        deterministic_context = self.review_service.build_review_context(
            report_date, include_public_context=True, include_benchmarks=True,
        )
        input_char_budget, output_token_limit = self._active_token_budget()
        evidence_pack = build_daily_position_review_evidence_pack(
            deterministic_context,
            daily_position_context_budget=input_char_budget,
        )
        runtime = ToolCallingRuntime(
            self.llm_service,
            max_rounds=4,
            max_observation_chars=input_char_budget,
            max_tokens=output_token_limit,
        )
        system_prompt, prompt_metadata = resolve_runtime_prompt(
            self.prompt_service,
            "daily_position_review_main",
            SYSTEM_PROMPT,
        )
        result = runtime.run(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": self._build_tool_user_prompt(report_date)},
            ],
            tools=self._tools(evidence_pack, report_date),
            response_format={"type": "json_object"},
            plan=[
                "读取 IBKR 账户和持仓快照，计算当日账户涨跌、持仓贡献、排行榜和风险集中度",
                "读取 Longbridge 公开行情、基准、估值、新闻和事件上下文",
                "解释主要贡献和拖累，识别账户风险变化",
                "输出明日关注清单和观察条件",
            ],
            initial_tool_calls=[
                {"name": "get_daily_position_review_context", "arguments": {"report_date": report_date}},
            ],
        )
        validated, raw_response, repair_error = self._validate_or_repair_llm_response(
            report_date=report_date,
            raw_response=result["content"],
            trace=result["trace"],
            deterministic_context=deterministic_context,
        )
        if validated is None and repair_error is not None:
            validated = self._build_fallback_review_payload(
                report_date=report_date,
                context=deterministic_context,
                parse_error=f"LLM output could not be parsed after {MAX_LLM_REPAIR_ATTEMPTS} repair attempts: {repair_error.message}",
            )
            raw_response = (
                f"{raw_response}\n\n"
                "--- fallback_reason ---\n"
                f"{repair_error.error_code}: {repair_error.message}"
            )

        provider_snapshot = self._provider_snapshot()
        metadata = build_metadata(
            agent_version=DAILY_POSITION_REVIEW_AGENT_VERSION,
            prompt_version=DAILY_POSITION_REVIEW_PROMPT_VERSION,
            schema_version=OUTPUT_SCHEMA_VERSION,
            toolset_version=DAILY_POSITION_REVIEW_TOOLSET_VERSION,
            evidence_builder_version=DAILY_POSITION_REVIEW_EVIDENCE_BUILDER_VERSION,
            agent_mode=AGENT_MODE_FIXED_EVIDENCE_WITH_SINGLE_TOOL,
            model_provider_snapshot=provider_snapshot,
        )
        metadata["prompt_metadata"] = {"daily_position_review_main": prompt_metadata}
        document = {
            **validated,
            "id": report_date,
            "review_type": "daily_position_review",
            "metadata": metadata,
            "evidence_summary": build_evidence_summary(evidence_pack, result["trace"]),
            "run_trace_summary": build_run_trace_summary(result["trace"]),
            "deterministic_context": self._compact_context_for_storage(deterministic_context),
            "run_trace": result["trace"],
            "raw_llm_response": raw_response,
            "model_provider_snapshot": provider_snapshot,
            "data_source_summary": deterministic_context.get("data_sources") or {},
        }
        if fallback_reason:
            document["fallback_reason"] = fallback_reason
            if "data_limitations" in document:
                document["data_limitations"] = [fallback_reason] + document["data_limitations"]
            else:
                document["data_limitations"] = [fallback_reason]
        return self.repository.save_review(document)

    def _tools(self, evidence_pack: dict, expected_report_date: str) -> list[AgentTool]:
        def handler(report_date: str) -> dict:
            if report_date != expected_report_date:
                return {
                    "error": f"report_date mismatch: requested {report_date}, expected {expected_report_date}",
                    "data_limitations": ["report_date mismatch in tool call"],
                }
            return evidence_pack

        return [
            AgentTool(
                "get_daily_position_review_context",
                "Read deterministic IBKR account/position attribution and Longbridge public market context for one report date.",
                {
                    "type": "object",
                    "properties": {"report_date": {"type": "string"}},
                    "required": ["report_date"],
                    "additionalProperties": False,
                },
                handler,
            )
        ]

    def _tools_subagent_cards(
        self,
        card_pack: DailyReviewEvidenceCardPack,
        compact_positions: list[dict],
        expected_report_date: str,
    ) -> list[AgentTool]:
        """Tools for sub-agent card mode."""
        def handler(report_date: str) -> dict:
            if report_date != expected_report_date:
                return {
                    "error": f"report_date mismatch: requested {report_date}, expected {expected_report_date}",
                    "data_limitations": ["report_date mismatch in tool call"],
                }

            # Build context with symbol cards and macro card
            # Core IBKR facts are complete; public data is in card format
            return {
                "report_date": card_pack.report_date,
                "account_facts": card_pack.account_facts,
                "positions": compact_positions,
                "rankings": card_pack.rankings,
                "risk": card_pack.risk,
                "attribution_quality": card_pack.attribution_quality,
                "benchmarks": card_pack.to_dict().get("benchmarks", {}),
                "symbol_cards": [card.to_dict() for card in card_pack.symbol_cards],
                "macro_card": card_pack.macro_card.to_dict() if card_pack.macro_card else None,
                "data_quality": card_pack.data_quality.to_dict(),
                "subagent_trace": card_pack.subagent_trace.to_dict(),
            }

        return [
            AgentTool(
                "get_daily_position_review_context",
                "Read IBKR account/position attribution and sub-agent evidence cards (symbol cards + macro card) for one report date.",
                {
                    "type": "object",
                    "properties": {"report_date": {"type": "string"}},
                    "required": ["report_date"],
                    "additionalProperties": False,
                },
                handler,
            )
        ]

    def _build_tool_user_prompt(self, report_date: str) -> str:
        schema = self._output_schema(report_date)
        return (
            "请调用工具生成每日持仓涨跌复盘。必须基于工具返回的确定性数字和公开市场数据。"
            "不要重新计算账户收益、仓位、贡献率或浮盈亏。"
            "重点解释：账户为什么涨跌、贡献和拖累来自哪里、风险结构如何变化、明天看什么。"
            "明日关注清单只能给观察条件，不要直接喊买卖。"
            "如果公开数据或行业/事件信息不足，必须写入 data_limitations。\n\n"
            f"复盘日期: {report_date}\n\n"
            f"最终只输出严格 JSON，所有 schema 字段都必须存在:\n{json.dumps(schema, ensure_ascii=False)}"
        )

    def _build_tool_user_prompt_subagent_cards(
        self,
        report_date: str,
        card_pack: DailyReviewEvidenceCardPack,
        compact_positions: list[dict],
    ) -> str:
        """Build user prompt for sub-agent card mode."""
        schema = self._output_schema(report_date)

        # Build compact card summary for prompt
        card_summary_lines = [f"报告日期: {report_date}", f"子 Agent 证据卡片模式: {len(card_pack.symbol_cards)} 个标的卡片"]
        for card in card_pack.symbol_cards:
            quality_marker = {"high": "✓", "medium": "○", "low": "✗"}.get(card.evidence_quality, "○")
            card_summary_lines.append(
                f"  {quality_marker} {card.symbol}: "
                f"账户贡献={card.account_impact.daily_pnl}, "
                f"涨跌={card.price_action.day_change_percent}%, "
                f"质量={card.evidence_quality}"
            )

        if card_pack.macro_card:
            card_summary_lines.append(
                f"  宏观卡片: regime={card_pack.macro_card.market_regime or 'N/A'}, "
                f"risk_sentiment={card_pack.macro_card.risk_sentiment or 'N/A'}"
            )

        card_summary_text = "\n".join(card_summary_lines)

        return (
            "请基于子 Agent 证据卡片生成每日持仓复盘。\n"
            "IBKR 核心账户事实（持仓、权重、盈亏贡献）来自确定性数据，不得修改。\n"
            "公开解释材料（新闻、估值、财报、技术面、宏观）来自子 Agent 摘要的证据卡片。\n"
            "不要重新计算 IBKR 数字，只基于卡片摘要进行解释和归因。\n"
            "明日关注清单只能给观察条件，不要直接喊买卖。\n"
            "如果公开数据不足，必须写入 data_limitations。\n\n"
            f"{card_summary_text}\n\n"
            f"最终只输出严格 JSON，所有 schema 字段都必须存在:\n{json.dumps(schema, ensure_ascii=False)}"
        )

    def _compact_positions_for_llm(self, positions: list[dict]) -> list[dict]:
        """
        Compact positions for LLM input.
        Keeps all key IBKR fields; removes raw Longbridge context.
        The full positions are preserved in deterministic_context for storage.
        """
        keys = (
            "symbol",
            "normalized_symbol",
            "quantity",
            "avg_cost",
            "average_cost",
            "average_cost_price",
            "current_price",
            "mark_price",
            "market_value",
            "position_value",
            "position_pct",
            "weight",
            "daily_pnl",
            "contribution_ratio",
            "unrealized_pnl",
            "unrealized_pnl_pct",
            "unrealized_pnl_percent",
            "realized_pnl",
            "daily_change_percent",
            "previous_day_change_percent",
            "is_major_contributor",
            "is_major_drag",
        )
        compacted = []
        for item in positions:
            if isinstance(item, dict):
                compacted.append({key: item.get(key) for key in keys if key in item})
        return compacted

    def _output_schema(self, report_date: str) -> dict:
        schema = {
            "report_date": report_date,
            "summary": "一句话总结今日账户表现",
            "account_conclusion": "今日账户结论",
            "attribution_summary": "账户涨跌归因",
            "major_contributors_analysis": [{"symbol": "AMD.US", "analysis": "..."}],
            "major_drags_analysis": [{"symbol": "NVDA.US", "analysis": "..."}],
            "focus_symbol_analyses": [
                {
                    "symbol": "AMD.US",
                    "price_action": "...",
                    "account_impact": "...",
                    "possible_reasons": ["..."],
                    "valuation_note": "...",
                    "cost_position_note": "...",
                    "watch_points": ["..."],
                    "data_limitations": ["..."],
                }
            ],
            "market_context": "市场和行业背景",
            "risk_analysis": "仓位风险变化",
            "tomorrow_watchlist": [
                {
                    "symbol": "AMD.US",
                    "reason": "...",
                    "key_levels": ["20日线", "前高"],
                    "events": ["..."],
                    "conditions": ["如果...则继续观察", "如果...则关注转弱"],
                }
            ],
            "operation_observation": "操作观察建议，不是强买强卖",
            "data_limitations": ["..."],
            "evidence_used": ["tool_name: brief reason"],
        }
        return schema

    def _validate_or_repair_llm_response(
        self,
        *,
        report_date: str,
        raw_response: str,
        trace: list[dict],
        deterministic_context: dict | None = None,
    ) -> tuple[dict | None, str, DailyPositionReviewAgentError | None]:
        candidate_response = raw_response
        response_history = [f"--- original_response ---\n{raw_response}"]
        last_error: DailyPositionReviewAgentError | None = None
        for attempt in range(MAX_LLM_REPAIR_ATTEMPTS + 1):
            try:
                parsed = extract_json_object(candidate_response)
                validated = self.validate_llm_output(parsed, expected_report_date=report_date, deterministic_context=deterministic_context)
                if attempt > 0:
                    response_history.append(f"--- final_validated_after_attempt_{attempt} ---")
                return validated, "\n\n".join(response_history), None
            except DailyPositionReviewAgentError as exc:
                last_error = exc
                if attempt >= MAX_LLM_REPAIR_ATTEMPTS:
                    break
                repair_attempt = attempt + 1
                repair_response = self._repair_llm_response(
                    report_date=report_date,
                    raw_response=candidate_response,
                    trace=trace,
                    validation_error=exc,
                    attempt=repair_attempt,
                )
                response_history.append(
                    f"--- repair_attempt_{repair_attempt}_for_{exc.error_code}: {exc.message} ---\n{repair_response}"
                )
                candidate_response = repair_response
        return None, "\n\n".join(response_history), last_error

    def _repair_llm_response(
        self,
        *,
        report_date: str,
        raw_response: str,
        trace: list[dict],
        validation_error: DailyPositionReviewAgentError,
        attempt: int,
    ) -> str:
        schema = self._output_schema(report_date)
        return self.llm_service.chat(
            [
                {"role": "system", "content": "你是 JSON 修复器，只输出符合 schema 的严格 JSON，不要输出 Markdown。"},
                {
                    "role": "user",
                    "content": (
                        "下面的模型输出不是有效每日持仓复盘 JSON。请基于请求、工具调用轨迹、错误信息和原始输出修复为严格 JSON。\n\n"
                        f"请求日期: {report_date}\n\n"
                        f"这是第 {attempt}/{MAX_LLM_REPAIR_ATTEMPTS} 次修复。上一次错误: "
                        f"{validation_error.error_code}: {validation_error.message}\n\n"
                        f"所有 schema 字段都必须存在，缺失字段请根据工具轨迹补齐；schema:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
                        f"工具轨迹:\n{json.dumps(trace, ensure_ascii=False, default=str)}\n\n"
                        f"原始输出:\n{raw_response}"
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=None,
            response_format={"type": "json_object"},
        )

    def validate_llm_output(self, payload: dict, expected_report_date: str, deterministic_context: dict | None = None) -> dict:
        if not isinstance(payload, dict):
            raise DailyPositionReviewAgentError("LLM_SCHEMA_INVALID", "LLM output must be an object")
        try:
            model = DailyPositionReviewOutput.model_validate({**payload, "report_date": payload.get("report_date") or expected_report_date})
            return normalize_daily_position_review_output(model.model_dump(), expected_report_date=expected_report_date, deterministic_context=deterministic_context)
        except ValidationError as exc:
            raise DailyPositionReviewAgentError("LLM_SCHEMA_INVALID", str(exc)) from exc
        except ValueError as exc:
            raise DailyPositionReviewAgentError("LLM_SCHEMA_INVALID", str(exc)) from exc

    def _build_fallback_review_payload(self, report_date: str, context: dict, parse_error: str) -> dict:
        overview = context.get("overview") or {}
        rankings = context.get("rankings") or {}
        risk = context.get("risk") or {}
        data_quality = context.get("data_quality") or {}
        top_contributors = rankings.get("profit_contributors") or []
        top_drags = rankings.get("loss_drags") or []
        top_weights = rankings.get("top_weights") or []
        focus_symbols = [str(symbol) for symbol in context.get("focus_symbols") or []]

        contributor_symbols = "、".join(item.get("symbol", "") for item in top_contributors[:3] if item.get("symbol")) or "暂无"
        drag_symbols = "、".join(item.get("symbol", "") for item in top_drags[:3] if item.get("symbol")) or "暂无"
        risk_flags = [str(item) for item in risk.get("risk_flags") or []]
        risk_summary = "；".join(risk_flags) if risk_flags else "当前没有明显集中度警报，仍需结合最大持仓和现金比例观察风险变化。"

        watch_symbols = focus_symbols[:5] or [item.get("symbol") for item in top_weights[:5] if item.get("symbol")]
        payload = {
            "report_date": report_date,
            "summary": overview.get("summary") or "复盘已生成，但 LLM 输出格式异常，本次先展示后端确定性数据摘要。",
            "account_conclusion": overview.get("summary") or "后端已完成账户涨跌和持仓贡献计算；LLM 解释部分因输出格式异常采用兜底摘要。",
            "attribution_summary": (
                f"当日账户盈亏为 {overview.get('daily_pnl')}，收益率为 {overview.get('daily_return_percent')}%。"
                f"主要贡献来自 {contributor_symbols}，主要拖累来自 {drag_symbols}。"
                "贡献、仓位、浮盈亏等数字均来自 IBKR 快照的后端计算。"
            ),
            "major_contributors_analysis": [
                {
                    "symbol": item.get("symbol"),
                    "analysis": (
                        f"当日盈亏 {item.get('daily_pnl')}，对账户当日盈亏贡献比例 {item.get('contribution_ratio')}，"
                        f"持仓权重 {item.get('weight')}。"
                    ),
                }
                for item in top_contributors[:5]
            ],
            "major_drags_analysis": [
                {
                    "symbol": item.get("symbol"),
                    "analysis": (
                        f"当日盈亏 {item.get('daily_pnl')}，对账户当日盈亏贡献比例 {item.get('contribution_ratio')}，"
                        f"持仓权重 {item.get('weight')}。"
                    ),
                }
                for item in top_drags[:5]
            ],
            "focus_symbol_analyses": [
                {
                    "symbol": symbol,
                    "price_action": "LLM 输出格式异常，价格异动解释待重新生成。",
                    "account_impact": "请参考下方确定性持仓贡献排行。",
                    "possible_reasons": [],
                    "valuation_note": "公开市场解释不足，未强行推断估值结论。",
                    "cost_position_note": "请参考持仓明细中的成本和浮盈亏位置。",
                    "watch_points": ["重新生成 LLM 复盘", "结合成交量、关键均线、财报和行业 ETF 表现继续观察"],
                    "data_limitations": [parse_error],
                }
                for symbol in watch_symbols[:5]
            ],
            "market_context": "LLM 输出不是有效 JSON，本次未可靠生成市场和行业解释；公开市场数据不足的部分不做强行归因。",
            "risk_analysis": risk_summary,
            "tomorrow_watchlist": [
                {
                    "symbol": symbol,
                    "reason": "重点持仓或当日异动标的，需要在下一交易日继续观察。",
                    "key_levels": [],
                    "events": [],
                    "conditions": ["关注成交量变化、关键均线或前高/前低位置", "关注行业 ETF 和大盘指数是否同步确认方向"],
                }
                for symbol in watch_symbols[:5]
            ],
            "operation_observation": "本次是格式异常后的兜底复盘，不给出强买强卖结论；建议在 LLM 输出恢复后重新生成完整解释。",
            "data_limitations": [
                parse_error,
                "本报告采用后端确定性数据兜底生成，个股原因、估值和新闻归因不完整。",
                *[str(item) for item in data_quality.get("warnings") or []],
            ],
            "evidence_used": [
                "get_daily_position_review_context: IBKR account and position attribution",
                "fallback: LLM response was not valid JSON",
            ],
        }
        return self.validate_llm_output(payload, expected_report_date=report_date, deterministic_context=context)

    def _compact_context_for_storage(self, context: dict) -> dict:
        compacted = {
            "report_date": context.get("report_date"),
            "data_sources": context.get("data_sources"),
            "overview": context.get("overview"),
            "positions": context.get("positions"),
            "rankings": {
                key: value[:5] if isinstance(value, list) else value
                for key, value in (context.get("rankings") or {}).items()
            },
            "risk": context.get("risk"),
            "benchmarks": context.get("benchmarks"),
            "focus_symbols": context.get("focus_symbols"),
            "attribution_quality": context.get("attribution_quality"),
            "data_quality": context.get("data_quality"),
        }
        return enforce_section_budget("daily_position_context", compacted)

    def _active_token_budget(self) -> tuple[int, int]:
        provider = self.llm_service.get_active_provider() if self.llm_service is not None else None
        input_token_limit = self._coerce_positive_int(
            getattr(provider, "input_token_limit", None),
            DEFAULT_INPUT_TOKEN_LIMIT,
        )
        output_token_limit = self._coerce_positive_int(
            getattr(provider, "output_token_limit", None),
            DEFAULT_OUTPUT_TOKEN_LIMIT,
        )
        return input_token_limit, output_token_limit

    def _provider_snapshot(self) -> dict:
        active_provider = self.llm_service.get_active_provider() if self.llm_service is not None else None
        if active_provider is None:
            return {}
        return {
            "provider_name": getattr(active_provider, "name", ""),
            "base_url": getattr(active_provider, "base_url", ""),
            "model": getattr(active_provider, "default_model", ""),
            "context_window_tokens": self._coerce_positive_int(
                getattr(active_provider, "context_window_tokens", None),
                DEFAULT_CONTEXT_WINDOW_TOKENS,
            ),
            "input_token_limit": self._coerce_positive_int(
                getattr(active_provider, "input_token_limit", None),
                DEFAULT_INPUT_TOKEN_LIMIT,
            ),
            "output_token_limit": self._coerce_positive_int(
                getattr(active_provider, "output_token_limit", None),
                DEFAULT_OUTPUT_TOKEN_LIMIT,
            ),
        }

    @staticmethod
    def _coerce_positive_int(value: Any, default: int) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return default
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default
