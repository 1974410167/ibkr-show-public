"""Live Mock Eval Executor - re-runs agents using mock data from Eval Cases."""

from __future__ import annotations

import json
from typing import Any, Protocol


class MockLLMClient(Protocol):
    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> str: ...


MOCK_PROMPTS_BY_AGENT: dict[str, str] = {
    "trade_review": (
        "你是一个交易复盘分析 Agent。以下是从评测用例中提供的 mock 数据，请基于这些数据生成交易复盘报告。\n\n"
        "## 用户请求\n{input}\n\n"
        "## Mock 上下文数据\n{mock_context}\n\n"
        "## Mock 工具输出\n{mock_tool_outputs}\n\n"
        "请以 JSON 格式输出复盘报告，包含以下字段：summary, overall_score (0-100), rating (good/fair/poor), data_limitations, strengths, weaknesses。"
    ),
    "trade_decision": (
        "你是一个交易决策分析 Agent。以下是从评测用例中提供的 mock 数据，请基于这些数据生成交易决策建议。\n\n"
        "## 用户请求\n{input}\n\n"
        "## Mock 上下文数据\n{mock_context}\n\n"
        "## Mock 工具输出\n{mock_tool_outputs}\n\n"
        "请以 JSON 格式输出决策建议，包含以下字段：decision_summary, action (buy/sell/hold), confidence (0-100), data_limitations, risk_factors。"
    ),
    "daily_position_review": (
        "你是一个每日持仓分析 Agent。以下是从评测用例中提供的 mock 数据，请基于这些数据生成持仓分析报告。\n\n"
        "## 用户请求\n{input}\n\n"
        "## Mock 上下文数据\n{mock_context}\n\n"
        "## Mock 工具输出\n{mock_tool_outputs}\n\n"
        "请以 JSON 格式输出持仓分析，包含以下字段：summary, account_conclusion, data_limitations, position_highlights, risk_alerts。"
    ),
    "account_copilot": (
        "你是一个账户助手 Agent。以下是从评测用例中提供的 mock 数据，请基于这些数据回答用户问题。\n\n"
        "## 用户请求\n{input}\n\n"
        "## Mock 上下文数据\n{mock_context}\n\n"
        "## Mock 工具输出\n{mock_tool_outputs}\n\n"
        "请以 JSON 格式输出回答，包含以下字段：answer, data_limitations。"
    ),
}


def _truncate(text: str, max_len: int = 8000) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


def _build_mock_messages(case: dict) -> list[dict[str, str]]:
    agent_name = case.get("agent_name", "unknown")
    template = MOCK_PROMPTS_BY_AGENT.get(agent_name)
    if template is None:
        return []

    input_data = case.get("input") or {}
    mock_context = case.get("mock_context") or {}
    mock_tool_outputs = case.get("mock_tool_outputs") or {}

    user_content = template.format(
        input=_truncate(json.dumps(input_data, ensure_ascii=False, indent=2)),
        mock_context=_truncate(json.dumps(mock_context, ensure_ascii=False, indent=2)),
        mock_tool_outputs=_truncate(json.dumps(mock_tool_outputs, ensure_ascii=False, indent=2)),
    )

    return [
        {"role": "system", "content": "你是一个金融分析 AI 助手。请严格基于提供的 mock 数据进行分析，不要编造数据。请以 JSON 格式输出结果。"},
        {"role": "user", "content": user_content},
    ]


def _parse_json_output(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {"summary": raw[:500], "raw_output": raw}


class LiveMockEvalExecutor:
    def __init__(self, llm_client: Any = None) -> None:
        self.llm_client = llm_client

    def is_agent_supported(self, agent_name: str) -> bool:
        return agent_name in MOCK_PROMPTS_BY_AGENT

    def run_case(self, case: dict) -> dict:
        agent_name = case.get("agent_name", "unknown")
        if not self.is_agent_supported(agent_name):
            return {
                "output": None,
                "error_code": "LIVE_MOCK_AGENT_NOT_SUPPORTED",
                "error_message": f"Agent '{agent_name}' does not support live_mock eval yet",
                "metadata": {"eval_mode": "live_mock", "agent_supported": False},
            }

        if self.llm_client is None:
            return {
                "output": None,
                "error_code": "LIVE_MOCK_NO_LLM_CLIENT",
                "error_message": "No LLM client available for live mock eval",
                "metadata": {"eval_mode": "live_mock", "llm_client_available": False},
            }

        messages = _build_mock_messages(case)
        if not messages:
            return {
                "output": None,
                "error_code": "LIVE_MOCK_PROMPT_BUILD_FAILED",
                "error_message": f"Failed to build mock prompt for agent '{agent_name}'",
                "metadata": {"eval_mode": "live_mock"},
            }

        try:
            raw_output = self.llm_client.chat(messages)
            output = _parse_json_output(raw_output)
            return {
                "output": output,
                "error_code": None,
                "error_message": None,
                "metadata": {
                    "eval_mode": "live_mock",
                    "live_mock_strategy": "prompt_adapter",
                    "graph_runner_executed": False,
                    "mock_context_used": bool(case.get("mock_context")),
                    "mock_tool_outputs_used": bool(case.get("mock_tool_outputs")),
                    "live_output_generated": True,
                    "actual_output": output,
                    "llm_raw_output_length": len(raw_output),
                },
            }
        except Exception as exc:
            return {
                "output": None,
                "error_code": "LIVE_MOCK_EXECUTION_FAILED",
                "error_message": str(exc)[:500],
                "metadata": {"eval_mode": "live_mock", "execution_error": str(exc)[:500]},
            }
