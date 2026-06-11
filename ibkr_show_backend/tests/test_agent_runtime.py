import json
import time

from app.agents.runtime import AgentTool, ToolCallingRuntime
from app.services.llm_observability import LLMCallMetadata, LLMCallResult, LLMUsage


class StubLLMService:
    def __init__(self, reasoning_round: int = 0) -> None:
        self.calls = 0
        self.kwargs = []
        self.messages = []
        self.reasoning_round = reasoning_round

    def chat_with_tools(self, messages, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)
        self.messages.append(messages)
        if self.calls == 1:
            response = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call-1", "type": "function", "function": {"name": "slow_tool", "arguments": json.dumps({"value": "a"})}},
                    {"id": "call-2", "type": "function", "function": {"name": "slow_tool", "arguments": json.dumps({"value": "b"})}},
                ],
            }
            if self.reasoning_round == 1:
                response["reasoning_content"] = "private reasoning"
                response["thinking"] = "private thinking"
            return response
        return {"role": "assistant", "content": '{"ok": true}', "tool_calls": []}


class MetadataLLMService(StubLLMService):
    def chat_with_tools_metadata(self, messages, **kwargs):
        message = self.chat_with_tools(messages, **{key: value for key, value in kwargs.items() if key not in {"call_type", "agent_name", "node_name", "prompt_metadata", "run_id", "session_id"}})
        prompt_metadata = kwargs.get("prompt_metadata") or {}
        return LLMCallResult(
            content=message.get("content"),
            message=message,
            raw_response_metadata={},
            call_metadata=LLMCallMetadata(
                call_id=f"call-{self.calls}",
                provider_id="provider-1",
                provider_name="Provider",
                provider_type="openai_compatible",
                model="model-a",
                call_type=kwargs.get("call_type") or "chat_with_tools",
                agent_name=kwargs.get("agent_name"),
                node_name=kwargs.get("node_name"),
                prompt_key=prompt_metadata.get("prompt_key"),
                prompt_version=prompt_metadata.get("version"),
                prompt_hash=prompt_metadata.get("content_hash"),
                prompt_source=prompt_metadata.get("source"),
                tool_calling=True,
                tool_count=len(kwargs.get("tools") or []),
                latency_ms=12,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                estimated_cost=0.001,
            ),
        )


class FinalRoundToolLLMService:
    def __init__(self) -> None:
        self.tool_calls = []
        self.chat_calls = 0

    def chat_with_tools_metadata(self, messages, **kwargs):
        self.tool_calls.append(kwargs)
        call_number = len(self.tool_calls)
        if call_number == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call-1", "type": "function", "function": {"name": "slow_tool", "arguments": json.dumps({"value": "a"})}},
                ],
            }
        else:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call-2", "type": "function", "function": {"name": "slow_tool", "arguments": json.dumps({"value": "b"})}},
                ],
            }
        return LLMCallResult(content=message.get("content"), message=message, raw_response_metadata={}, call_metadata=None)

    def chat_with_metadata(self, messages, **kwargs):
        self.chat_calls += 1
        return LLMCallResult(
            content='{"ok": true, "source": "no_tools_synthesis"}',
            message={"role": "assistant", "content": '{"ok": true, "source": "no_tools_synthesis"}'},
            raw_response_metadata={},
            call_metadata=None,
        )


def test_tool_calling_runtime_executes_tool_calls_in_parallel() -> None:
    def slow_tool(value: str) -> dict:
        time.sleep(0.2)
        return {"value": value}

    runtime = ToolCallingRuntime(StubLLMService(), max_parallel_tools=2)
    started = time.perf_counter()
    result = runtime.run(
        messages=[{"role": "user", "content": "run"}],
        tools=[
            AgentTool(
                "slow_tool",
                "Slow test tool",
                {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                slow_tool,
            )
        ],
    )

    assert time.perf_counter() - started < 0.35
    assert result["content"] == '{"ok": true}'
    assert [item["event"] for item in result["trace"]].count("tool_start") == 2
    assert [item["event"] for item in result["trace"]].count("tool_finish") == 2


def test_runtime_observation_serialization_strips_engine_payload() -> None:
    runtime = ToolCallingRuntime(StubLLMService(), max_observation_chars=50000)
    observation = {
        "ok": True,
        "tool": "candlesticks",
        "data": {
            "ok": True,
            "data": {"sample_points": 2},
            "engine_payload": {
                "candles": [{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100}],
            },
        },
    }

    serialized = runtime._serialize_observation(observation)

    assert "engine_payload" not in serialized
    assert '"candles"' not in serialized
    assert "sample_points" in serialized


def test_tool_calling_runtime_passes_max_tokens_to_llm() -> None:
    llm_service = StubLLMService()
    runtime = ToolCallingRuntime(llm_service, max_tokens=4096)

    result = runtime.run(messages=[{"role": "user", "content": "finish"}], tools=[])

    assert result["content"] == '{"ok": true}'
    assert llm_service.kwargs[0]["max_tokens"] == 4096


def test_tool_calling_runtime_trace_includes_llm_call_metadata() -> None:
    llm_service = MetadataLLMService()
    runtime = ToolCallingRuntime(
        llm_service,
        agent_name="trade_review",
        node_name="compose_trade_review",
        prompt_metadata={"prompt_key": "trade_review_main", "version": "v2", "content_hash": "abc", "source": "admin_active"},
    )

    result = runtime.run(messages=[{"role": "user", "content": "finish"}], tools=[])

    llm_finish = next(item for item in result["trace"] if item["event"] == "llm_finish")
    assert llm_finish["call_id"] == "call-1"
    assert llm_finish["provider_name"] == "Provider"
    assert llm_finish["model"] == "model-a"
    assert llm_finish["prompt_tokens"] == 10
    assert llm_finish["completion_tokens"] == 5
    assert llm_finish["total_tokens"] == 15
    assert llm_finish["prompt_key"] == "trade_review_main"
    assert llm_finish["prompt_version"] == "v2"
    assert llm_finish["prompt_hash"] == "abc"
    assert llm_finish["prompt_source"] == "admin_active"


def test_strip_reasoning_fields_removes_private_fields() -> None:
    """_strip_reasoning_fields removes reasoning, reasoning_content, thinking."""
    message = {
        "role": "assistant",
        "content": "final answer",
        "reasoning_content": "private",
        "thinking": "private",
        "reasoning": "private",
        "tool_calls": [],
    }
    stripped = ToolCallingRuntime._strip_reasoning_fields(message)
    assert "reasoning_content" not in stripped
    assert "thinking" not in stripped
    assert "reasoning" not in stripped
    assert stripped["content"] == "final answer"
    assert stripped["role"] == "assistant"


def test_runtime_strips_reasoning_from_response_before_appending() -> None:
    """ToolCallingRuntime preserves reasoning internally but strips it from returned messages."""
    def slow_tool(value: str) -> dict:
        return {"value": value}

    llm_service = StubLLMService(reasoning_round=1)
    runtime = ToolCallingRuntime(llm_service)

    result = runtime.run(
        messages=[{"role": "user", "content": "run"}],
        tools=[
            AgentTool(
                "slow_tool",
                "Slow test tool",
                {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                slow_tool,
            )
        ],
    )

    assert result["content"] == '{"ok": true}'
    assert llm_service.kwargs[0]["preserve_provider_reasoning"] is True
    assert llm_service.kwargs[1]["preserve_provider_reasoning"] is True
    second_round_messages = llm_service.messages[1]
    assistant_messages = [msg for msg in second_round_messages if msg.get("role") == "assistant"]
    assert assistant_messages
    assert assistant_messages[0]["reasoning_content"] == "private reasoning"
    assert assistant_messages[0]["thinking"] == "private thinking"
    for msg in result["messages"]:
        if msg.get("role") == "assistant":
            assert "reasoning_content" not in msg
            assert "thinking" not in msg
            assert "reasoning" not in msg


def test_tool_calling_runtime_forces_tool_choice_none_on_final_round() -> None:
    def slow_tool(value: str) -> dict:
        return {"value": value}

    llm_service = StubLLMService()
    runtime = ToolCallingRuntime(llm_service, max_rounds=2)
    result = runtime.run(
        messages=[{"role": "user", "content": "run"}],
        tools=[
            AgentTool(
                "slow_tool",
                "Slow test tool",
                {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                slow_tool,
            )
        ],
    )

    assert result["content"] == '{"ok": true}'
    assert llm_service.kwargs[0]["tool_choice"] == "auto"
    assert llm_service.kwargs[1]["tool_choice"] == "none"
    assert any(item["event"] == "final_round_forced_synthesis" for item in result["trace"])


def test_tool_calling_runtime_blocks_final_round_tool_call_and_synthesizes() -> None:
    def slow_tool(value: str) -> dict:
        return {"value": value}

    llm_service = FinalRoundToolLLMService()
    runtime = ToolCallingRuntime(llm_service, max_rounds=2)
    result = runtime.run(
        messages=[{"role": "user", "content": "run"}],
        tools=[
            AgentTool(
                "slow_tool",
                "Slow test tool",
                {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                slow_tool,
            )
        ],
        response_format={"type": "json_object"},
    )

    events = [item["event"] for item in result["trace"]]
    assert result["content"] == '{"ok": true, "source": "no_tools_synthesis"}'
    assert llm_service.tool_calls[1]["tool_choice"] == "none"
    assert llm_service.chat_calls == 1
    assert "tool_call_blocked_on_final_round" in events
    assert "no_tools_synthesis_finish" in events


def test_synthesize_without_tools_passes_preserve_provider_reasoning() -> None:
    """_synthesize_without_tools passes preserve_provider_reasoning=True for DeepSeek compatibility."""

    class SynthesisTrackLLMService:
        def __init__(self) -> None:
            self.tool_kwargs = []
            self.chat_kwargs = []

        def chat_with_tools_metadata(self, messages, **kwargs):
            self.tool_kwargs.append(kwargs)
            # Return tool_calls to trigger synthesis path
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call-1", "type": "function", "function": {"name": "noop", "arguments": "{}"}},
                ],
                "reasoning_content": "step 1 reasoning",
            }
            return LLMCallResult(content=None, message=message, raw_response_metadata={}, call_metadata=None)

        def chat_with_metadata(self, messages, **kwargs):
            self.chat_kwargs.append(kwargs)
            return LLMCallResult(
                content='{"ok": true}',
                message={"role": "assistant", "content": '{"ok": true}'},
                raw_response_metadata={},
                call_metadata=None,
            )

    def noop() -> dict:
        return {}

    llm_service = SynthesisTrackLLMService()
    runtime = ToolCallingRuntime(llm_service, max_rounds=1)
    result = runtime.run(
        messages=[{"role": "user", "content": "run"}],
        tools=[
            AgentTool(
                "noop",
                "No-op tool",
                {"type": "object", "properties": {}, "additionalProperties": False},
                noop,
            )
        ],
    )

    assert result["content"] == '{"ok": true}'
    # The synthesis call should pass preserve_provider_reasoning=True
    assert llm_service.chat_kwargs[0]["preserve_provider_reasoning"] is True
    # Final returned messages should not contain reasoning_content
    for msg in result["messages"]:
        if msg.get("role") == "assistant":
            assert "reasoning_content" not in msg
            assert "thinking" not in msg
