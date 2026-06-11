from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable

from app.agents.context_budget import enforce_section_budget
from app.services.llm_service import PROVIDER_PRIVATE_REASONING_FIELDS, LLMService


class AgentRuntimeError(RuntimeError):
    """Raised when a tool-calling agent cannot complete safely."""


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    output_budget_section: str | None = None
    output_compactor: Callable[[Any], Any] | None = None
    include_output_in_trace: bool = False

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
                "strict": True,
            },
        }


@dataclass
class ToolExecution:
    tool_call_id: str
    name: str
    arguments: dict[str, Any]
    output: Any
    ok: bool
    latency_ms: int = 0
    observation_meta: dict[str, Any] | None = None


class ToolCallingRuntime:
    def __init__(
        self,
        llm_service: LLMService,
        *,
        max_rounds: int = 6,
        max_parallel_tools: int = 6,
        max_observation_chars: int = 12000,
        max_tokens: int | None = None,
        agent_name: str | None = None,
        node_name: str | None = None,
        prompt_metadata: dict | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        monitoring_service: Any | None = None,
        call_type: str = "chat_with_tools",
    ) -> None:
        self.llm_service = llm_service
        self.max_rounds = max_rounds
        self.max_parallel_tools = max_parallel_tools
        self.max_observation_chars = max_observation_chars
        self.max_tokens = max_tokens
        self.agent_name = agent_name
        self.node_name = node_name
        self.prompt_metadata = prompt_metadata
        self.run_id = run_id
        self.session_id = session_id
        self.task_id = task_id
        self.monitoring_service = monitoring_service
        self.call_type = call_type

    def run(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[AgentTool],
        response_format: dict | None = None,
        plan: list[str] | None = None,
        initial_tool_calls: list[dict[str, Any]] | None = None,
        require_initial_tool_call: bool = False,
        fallback_tool_calls: list[dict[str, Any]] | None = None,
        agent_name: str | None = None,
        node_name: str | None = None,
        prompt_metadata: dict | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        call_type: str | None = None,
    ) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []
        if plan:
            trace.append({"event": "plan", "steps": plan, "created_at_ms": int(time.time() * 1000)})

        tool_by_name = {tool.name: tool for tool in tools}
        openai_tools = [tool.to_openai_tool() for tool in tools]
        conversation = list(messages)

        if initial_tool_calls:
            trace.append(
                {
                    "event": "initial_tool_plan",
                    "summary": "Executing default read-only tool set before LLM synthesis.",
                    "created_at_ms": int(time.time() * 1000),
                }
            )
            tool_calls = self._build_fallback_tool_calls(initial_tool_calls)
            executions = self._execute_tool_calls(tool_calls, tool_by_name, trace)
            self._append_synthetic_observations(
                conversation,
                executions,
                intro=(
                    "下面是系统按默认执行计划并行完成的只读工具调用结果。"
                    "请优先基于这些工具结果输出最终严格 JSON；只有确实缺少必要信息时才继续调用工具。"
                ),
            )

        for round_index in range(1, self.max_rounds + 1):
            is_final_round = round_index == self.max_rounds
            if is_final_round:
                trace.append(
                    {
                        "event": "final_round_forced_synthesis",
                        "round": round_index,
                        "summary": "Final round forces no tool calls and requires strict JSON synthesis.",
                        "created_at_ms": int(time.time() * 1000),
                    }
                )
                conversation.append(
                    {
                        "role": "user",
                        "content": "这是最后一轮，请不要再调用工具，只能基于已有工具结果输出严格 JSON。",
                    }
                )
            started = time.perf_counter()
            trace.append({"event": "llm_start", "round": round_index, "created_at_ms": int(time.time() * 1000)})
            call_metadata = None
            try:
                message, call_metadata = self._chat_with_optional_tools(
                    conversation=conversation,
                    openai_tools=openai_tools,
                    response_format=response_format,
                    tool_choice="none" if is_final_round else "auto",
                    call_type=call_type or self.call_type,
                    agent_name=agent_name or self.agent_name,
                    node_name=node_name or self.node_name,
                    prompt_metadata=prompt_metadata or self.prompt_metadata,
                    run_id=run_id or self.run_id,
                    session_id=session_id or self.session_id,
                )
            except Exception as exc:
                if not is_final_round:
                    raise
                trace.append(
                    {
                        "event": "final_round_tool_choice_none_unsupported",
                        "round": round_index,
                        "error": str(exc)[:200],
                        "created_at_ms": int(time.time() * 1000),
                    }
                )
                message, call_metadata = self._synthesize_without_tools(
                    conversation=conversation,
                    response_format=response_format,
                    call_type=call_type or self.call_type,
                    agent_name=agent_name or self.agent_name,
                    node_name=node_name or self.node_name,
                    prompt_metadata=prompt_metadata or self.prompt_metadata,
                    run_id=run_id or self.run_id,
                    session_id=session_id or self.session_id,
                    trace=trace,
                )
            self._record_llm_metric(call_metadata)
            trace.append(
                {
                    "event": "llm_finish",
                    "round": round_index,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "created_at_ms": int(time.time() * 1000),
                    **self._llm_trace_metadata(call_metadata),
                }
            )
            tool_calls = message.get("tool_calls") or []
            if tool_calls and is_final_round:
                trace.append(
                    {
                        "event": "tool_call_blocked_on_final_round",
                        "round": round_index,
                        "blocked_tool_count": len(tool_calls),
                        "blocked_tools": [
                            ((call.get("function") or {}).get("name") or "unknown_tool")
                            for call in tool_calls
                            if isinstance(call, dict)
                        ],
                        "created_at_ms": int(time.time() * 1000),
                    }
                )
                message, call_metadata = self._synthesize_without_tools(
                    conversation=conversation,
                    response_format=response_format,
                    call_type=call_type or self.call_type,
                    agent_name=agent_name or self.agent_name,
                    node_name=node_name or self.node_name,
                    prompt_metadata=prompt_metadata or self.prompt_metadata,
                    run_id=run_id or self.run_id,
                    session_id=session_id or self.session_id,
                    trace=trace,
                )
                self._record_llm_metric(call_metadata)
                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    raise AgentRuntimeError("Agent final synthesis did not produce JSON")
            if not tool_calls:
                if require_initial_tool_call and round_index == 1 and fallback_tool_calls:
                    tool_calls = self._build_fallback_tool_calls(fallback_tool_calls)
                    trace.append(
                        {
                            "event": "fallback_tool_plan",
                            "round": round_index,
                            "summary": "Model did not request tools; executing default read-only tool set.",
                            "created_at_ms": int(time.time() * 1000),
                        }
                    )
                    executions = self._execute_tool_calls(tool_calls, tool_by_name, trace)
                    self._append_synthetic_observations(
                        conversation,
                        executions,
                        intro=(
                            "模型上一轮没有发起工具调用。下面是系统按默认执行计划并行完成的只读工具调用结果。"
                            "请只基于这些工具结果和已知限制输出最终严格 JSON，不要再声称尚未调用工具。"
                        ),
                    )
                    continue
                content = str(message.get("content") or "")
                trace.append({"event": "final", "round": round_index, "created_at_ms": int(time.time() * 1000)})
                return {"content": content, "trace": trace, "messages": self._strip_reasoning_from_messages(conversation + [message])}

            conversation.append(message)
            executions = self._execute_tool_calls(tool_calls, tool_by_name, trace)
            for execution in executions:
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": execution.tool_call_id,
                        "content": self._serialize_observation(
                            {
                                "ok": execution.ok,
                                "tool": execution.name,
                                "arguments": execution.arguments,
                                "data": execution.output,
                            }
                        ),
                    }
                )

        return self._force_no_tools_final_answer(
            conversation=conversation,
            response_format=response_format,
            call_type=call_type or self.call_type,
            agent_name=agent_name or self.agent_name,
            node_name=node_name or self.node_name,
            prompt_metadata=prompt_metadata or self.prompt_metadata,
            run_id=run_id or self.run_id,
            session_id=session_id or self.session_id,
            task_id=task_id or self.task_id,
            trace=trace,
        )

    def _chat_with_optional_tools(
        self,
        *,
        conversation: list[dict[str, Any]],
        openai_tools: list[dict[str, Any]],
        response_format: dict | None,
        tool_choice: str | dict,
        call_type: str,
        agent_name: str | None,
        node_name: str | None,
        prompt_metadata: dict | None,
        run_id: str | None,
        session_id: str | None,
    ) -> tuple[dict[str, Any], Any]:
        if hasattr(self.llm_service, "chat_with_tools_metadata"):
            result = self.llm_service.chat_with_tools_metadata(
                conversation,
                tools=openai_tools,
                temperature=None,
                max_tokens=self.max_tokens,
                response_format=response_format,
                tool_choice=tool_choice,
                preserve_provider_reasoning=True,
                call_type=call_type,
                agent_name=agent_name,
                node_name=node_name,
                prompt_metadata=prompt_metadata,
                run_id=run_id,
                session_id=session_id,
            )
            return result.message or {}, result.call_metadata
        message = self.llm_service.chat_with_tools(
            conversation,
            tools=openai_tools,
            temperature=None,
            max_tokens=self.max_tokens,
            response_format=response_format,
            tool_choice=tool_choice,
            preserve_provider_reasoning=True,
        )
        return message, None

    def _synthesize_without_tools(
        self,
        *,
        conversation: list[dict[str, Any]],
        response_format: dict | None,
        call_type: str,
        agent_name: str | None,
        node_name: str | None,
        prompt_metadata: dict | None,
        run_id: str | None,
        session_id: str | None,
        trace: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], Any]:
        started = time.perf_counter()
        synthesis_messages = conversation + [
            {
                "role": "user",
                "content": "不要再调用任何工具。请只基于以上已有 observations 输出最终严格 JSON object，不要输出 Markdown。",
            }
        ]
        if hasattr(self.llm_service, "chat_with_metadata"):
            result = self.llm_service.chat_with_metadata(
                synthesis_messages,
                temperature=None,
                max_tokens=self.max_tokens,
                response_format=response_format,
                call_type=call_type,
                agent_name=agent_name,
                node_name=node_name,
                prompt_metadata=prompt_metadata,
                run_id=run_id,
                session_id=session_id,
                preserve_provider_reasoning=True,
            )
            message = {"role": "assistant", "content": result.content or "", "tool_calls": []}
            call_metadata = result.call_metadata
        else:
            content = self.llm_service.chat(
                synthesis_messages,
                temperature=None,
                max_tokens=self.max_tokens,
                response_format=response_format,
            )
            message = {"role": "assistant", "content": content, "tool_calls": []}
            call_metadata = None
        trace.append(
            {
                "event": "no_tools_synthesis_finish",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "created_at_ms": int(time.time() * 1000),
                **self._llm_trace_metadata(call_metadata),
            }
        )
        return message, call_metadata

    def _force_no_tools_final_answer(
        self,
        *,
        conversation: list[dict[str, Any]],
        response_format: dict | None,
        call_type: str,
        agent_name: str | None,
        node_name: str | None,
        prompt_metadata: dict | None,
        run_id: str | None,
        session_id: str | None,
        task_id: str | None,
        trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        trace.append(
            {
                "event": "final_round_forced_synthesis",
                "summary": "Max rounds exhausted; attempting no-tools synthesis instead of raising max_rounds.",
                "created_at_ms": int(time.time() * 1000),
            }
        )
        message, call_metadata = self._synthesize_without_tools(
            conversation=conversation,
            response_format=response_format,
            call_type=call_type,
            agent_name=agent_name,
            node_name=node_name,
            prompt_metadata=prompt_metadata,
            run_id=run_id,
            session_id=session_id,
            trace=trace,
        )
        self._record_llm_metric(call_metadata)
        if message.get("tool_calls"):
            raise AgentRuntimeError("Agent final synthesis did not produce JSON")
        content = str(message.get("content") or "")
        trace.append({"event": "final", "round": self.max_rounds, "created_at_ms": int(time.time() * 1000)})
        return {"content": content, "trace": trace, "messages": self._strip_reasoning_from_messages(conversation + [message])}

    def _execute_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        tool_by_name: dict[str, AgentTool],
        trace: list[dict[str, Any]],
    ) -> list[ToolExecution]:
        executions: list[ToolExecution] = []
        with ThreadPoolExecutor(max_workers=min(self.max_parallel_tools, max(1, len(tool_calls)))) as executor:
            future_map = {}
            for raw_call in tool_calls:
                function = raw_call.get("function") or {}
                name = str(function.get("name") or "")
                arguments = self._parse_arguments(function.get("arguments"))
                call_id = str(raw_call.get("id") or f"tool-{len(future_map) + 1}")
                trace.append(
                    {
                        "event": "tool_start",
                        "tool_call_id": call_id,
                        "tool": name,
                        "arguments": arguments,
                        "created_at_ms": int(time.time() * 1000),
                    }
                )
                future_map[executor.submit(self._run_tool, call_id, name, arguments, tool_by_name)] = (call_id, name, arguments)

            for future in as_completed(future_map):
                started_call_id, started_name, started_args = future_map[future]
                try:
                    execution = future.result()
                except Exception as exc:  # defensive: _run_tool should normally catch this
                    execution = ToolExecution(started_call_id, started_name, started_args, {"error": str(exc)}, False)
                trace_item = {
                    "event": "tool_finish" if execution.ok else "tool_error",
                    "tool_call_id": execution.tool_call_id,
                    "tool": execution.name,
                    "arguments": execution.arguments,
                    "ok": execution.ok,
                    "latency_ms": execution.latency_ms,
                    "summary": self._summarize_output(execution.output),
                    "observation": self._observation_trace_meta(execution),
                    "created_at_ms": int(time.time() * 1000),
                }
                tool = tool_by_name.get(execution.name)
                if tool is not None and tool.include_output_in_trace:
                    trace_item["output"] = execution.output
                trace.append(trace_item)
                executions.append(execution)

        execution_order = {str(call.get("id") or ""): index for index, call in enumerate(tool_calls)}
        executions.sort(key=lambda item: execution_order.get(item.tool_call_id, len(execution_order)))
        return executions

    def _run_tool(
        self,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
        tool_by_name: dict[str, AgentTool],
    ) -> ToolExecution:
        tool = tool_by_name.get(name)
        if tool is None:
            return ToolExecution(call_id, name, arguments, {"error": f"Unknown tool: {name}"}, False)
        started = time.perf_counter()
        try:
            output = tool.handler(**arguments)
            if tool.output_compactor is not None:
                output = tool.output_compactor(output)
            elif tool.output_budget_section is not None:
                output = enforce_section_budget(tool.output_budget_section, output)
            ok = not (isinstance(output, dict) and output.get("ok") is False)
            latency_ms = int((time.perf_counter() - started) * 1000)
            execution = ToolExecution(call_id, name, arguments, output, ok, latency_ms)
            self._record_tool_metric(execution)
            return execution
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            execution = ToolExecution(call_id, name, arguments, {"error": str(exc)}, False, latency_ms)
            self._record_tool_metric(execution)
            return execution

    def _record_tool_metric(self, execution: ToolExecution) -> None:
        if self.monitoring_service is None:
            return
        output = execution.output if isinstance(execution.output, dict) else {}
        diagnostics = output.get("tool_call") if isinstance(output.get("tool_call"), dict) else {}
        error_message = output.get("message") or output.get("error")
        parsed_fields = diagnostics.get("parsed_fields") if isinstance(diagnostics.get("parsed_fields"), list) else []
        missing_fields = diagnostics.get("missing_fields") if isinstance(diagnostics.get("missing_fields"), list) else []
        try:
            self.monitoring_service.record_tool_call(
                run_id=self.run_id,
                task_id=self.task_id,
                session_id=self.session_id,
                agent_name=self.agent_name,
                node_name=self.node_name,
                tool_name=execution.name,
                tool_domain="longbridge" if self.agent_name == "trade_decision" else None,
                ok=execution.ok,
                latency_ms=execution.latency_ms,
                error_code=output.get("error_code") or diagnostics.get("error_type"),
                error_message=error_message,
                source="runtime",
                metadata={"tool_call_id": execution.tool_call_id},
                empty_result=diagnostics.get("empty_result"),
                raw_ok=diagnostics.get("success"),
                compact_ok=output.get("ok") if "ok" in output else execution.ok,
                parsed_fields_count=len(parsed_fields),
                missing_fields_count=len(missing_fields),
                fallback_used=False,
            )
        except Exception:
            return

    def _record_llm_metric(self, call_metadata: Any) -> None:
        if self.monitoring_service is None or call_metadata is None:
            return
        usage = getattr(call_metadata, "usage", None)
        try:
            self.monitoring_service.record_llm_call(
                run_id=self.run_id,
                task_id=self.task_id,
                session_id=self.session_id,
                agent_name=getattr(call_metadata, "agent_name", None) or self.agent_name,
                node_name=getattr(call_metadata, "node_name", None) or self.node_name,
                provider=getattr(call_metadata, "provider_name", None) or getattr(call_metadata, "provider_type", None) or "unknown",
                model=getattr(call_metadata, "model", None) or "unknown",
                call_type=getattr(call_metadata, "call_type", None) or self.call_type,
                ok=bool(getattr(call_metadata, "ok", True)),
                latency_ms=int(getattr(call_metadata, "latency_ms", 0) or 0),
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
                error_code=getattr(call_metadata, "error_code", None),
                error_message=getattr(call_metadata, "error_message", None),
                metadata={"call_id": getattr(call_metadata, "call_id", "")},
            )
        except Exception:
            return

    def _parse_arguments(self, raw_arguments: Any) -> dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if raw_arguments in (None, ""):
            return {}
        try:
            value = json.loads(str(raw_arguments))
        except json.JSONDecodeError as exc:
            raise AgentRuntimeError("Tool call arguments are not valid JSON") from exc
        if not isinstance(value, dict):
            raise AgentRuntimeError("Tool call arguments must be a JSON object")
        return value

    def _serialize_observation(self, value: Any) -> str:
        text = json.dumps(self._strip_engine_payload(value), ensure_ascii=False, default=str)
        if len(text) <= self.max_observation_chars:
            return text
        preview_limit = max(200, self.max_observation_chars - 300)
        fallback = {
            "truncated": True,
            "reason": "observation exceeded runtime max chars",
            "original_size": len(text),
            "final_size": None,
            "preview": text[:preview_limit].rstrip(),
            "data_limitations": ["Tool observation was truncated by runtime"],
        }
        fallback["final_size"] = len(json.dumps(fallback, ensure_ascii=False, default=str))
        return json.dumps(fallback, ensure_ascii=False, default=str)

    @classmethod
    def _strip_engine_payload(cls, value: Any) -> Any:
        """Remove deterministic-engine payloads before sending tool results to the LLM."""
        if isinstance(value, dict):
            return {
                key: cls._strip_engine_payload(item)
                for key, item in value.items()
                if key != "engine_payload"
            }
        if isinstance(value, list):
            return [cls._strip_engine_payload(item) for item in value]
        return value

    def _observation_trace_meta(self, execution: ToolExecution) -> dict[str, Any]:
        observation = {
            "ok": execution.ok,
            "tool": execution.name,
            "arguments": execution.arguments,
            "data": execution.output,
        }
        original_size = len(json.dumps(observation, ensure_ascii=False, default=str))
        serialized = self._serialize_observation(observation)
        return {
            "original_size": original_size,
            "final_size": len(serialized),
            "truncated": original_size > self.max_observation_chars,
        }

    def _append_synthetic_observations(self, conversation: list[dict[str, Any]], executions: list[ToolExecution], *, intro: str) -> None:
        conversation.append({"role": "user", "content": intro})
        for execution in executions:
            observation = {
                "ok": execution.ok,
                "tool": execution.name,
                "arguments": execution.arguments,
                "data": execution.output,
            }
            conversation.append(
                {
                    "role": "user",
                    "content": f"工具结果 {execution.name}:\n{self._serialize_observation(observation)}",
                }
            )

    def _summarize_output(self, value: Any) -> str:
        if isinstance(value, dict):
            keys = ", ".join(list(value.keys())[:8])
            return f"object keys: {keys}" if keys else "empty object"
        if isinstance(value, list):
            return f"list length: {len(value)}"
        text = str(value)
        return text if len(text) <= 160 else text[:157].rstrip() + "..."

    @staticmethod
    def _strip_reasoning_fields(message: dict[str, Any]) -> dict[str, Any]:
        """Remove provider-private reasoning fields from an LLM response message.

        This prevents reasoning_content from being forwarded to subsequent
        requests, which would trigger 400 errors on providers that enforce
        thinking-mode round-tripping.
        """
        return {
            key: value
            for key, value in message.items()
            if key not in PROVIDER_PRIVATE_REASONING_FIELDS
        }

    @classmethod
    def _strip_reasoning_from_messages(cls, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [cls._strip_reasoning_fields(message) if isinstance(message, dict) else message for message in messages]

    def _build_fallback_tool_calls(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tool_calls = []
        for index, call in enumerate(calls, start=1):
            name = str(call.get("name") or "")
            arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            tool_calls.append(
                {
                    "id": f"fallback-{index}-{name}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            )
        return tool_calls

    def _llm_trace_metadata(self, call_metadata: Any) -> dict[str, Any]:
        if call_metadata is None:
            return {}
        usage = getattr(call_metadata, "usage", None)
        return {
            "call_id": getattr(call_metadata, "call_id", None),
            "provider_name": getattr(call_metadata, "provider_name", None),
            "model": getattr(call_metadata, "model", None),
            "agent_name": getattr(call_metadata, "agent_name", None),
            "node_name": getattr(call_metadata, "node_name", None),
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
            "estimated_cost": getattr(call_metadata, "estimated_cost", None),
            "prompt_key": getattr(call_metadata, "prompt_key", None),
            "prompt_version": getattr(call_metadata, "prompt_version", None),
            "prompt_hash": getattr(call_metadata, "prompt_hash", None),
            "prompt_source": getattr(call_metadata, "prompt_source", None),
        }
