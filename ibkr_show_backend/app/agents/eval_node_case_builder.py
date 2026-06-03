from __future__ import annotations

from typing import Any

from app.agents.eval_harness import EvalCase, new_eval_case_id, utc_now_iso


# 单字段最大长度（用于 output 截断）
_MAX_OUTPUT_FIELD_LEN = 2000
# 总 output dict 序列化后最大长度
_MAX_OUTPUT_TOTAL_LEN = 4000

# 禁止复制到 case 的敏感字段名（防止 API key / token / 密钥泄露）
_SENSITIVE_KEYWORDS = (
    "api_key", "apikey", "secret", "token", "authorization", "auth", "cookie",
    "password", "passwd", "credential",
)


_NODE_EXPECTED_BEHAVIOR: dict[str, dict[str, Any]] = {
    "market_trend": {
        "should": [
            "围绕价格走势、成交量、均线、波动率、技术形态展开",
            "应说明时间周期和趋势判断依据",
            "应说明不确定性和数据限制",
        ],
    },
    "fundamental_valuation": {
        "should": [
            "围绕收入、利润、现金流、增长、行业对比展开",
            "应避免机械 PE 或单指标判断",
            "应说明估值假设和不确定性",
        ],
    },
    "event_catalyst": {
        "should": [
            "应围绕财报、发布会、监管、并购、订单、政策等具体事件展开",
            "应区分已发生事件和预期事件",
            "应说明证据或信息来源",
        ],
    },
    "risk_control": {
        "should": [
            "应明确仓位、分批、止损、回撤等风险约束",
            "应说明用户现有持仓和现金比例",
            "应避免满仓、梭哈等极端表达",
        ],
    },
    "final_decision": {
        "should": [
            "应基于前面节点结论，给出明确动作和理由",
            "应包含风险控制、分批、止损或条件",
            "应避免弱信号叠加的强买入结论",
        ],
    },
}


def _default_expected_behavior(node_name: str | None) -> dict[str, Any]:
    if node_name and node_name in _NODE_EXPECTED_BEHAVIOR:
        return dict(_NODE_EXPECTED_BEHAVIOR[node_name])
    return {
        "should": [
            "输出应围绕该节点职责展开",
            "应说明不确定性和数据限制",
        ],
    }


def _truncate(value: Any, limit: int = _MAX_OUTPUT_FIELD_LEN) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 3] + "..."
    return value


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lower = key.lower()
    return any(s in lower for s in _SENSITIVE_KEYWORDS)


def _scrub_sensitive(value: Any) -> Any:
    """递归移除敏感字段。dict / list 递归处理；字符串保留。"""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            if _is_sensitive_key(k):
                continue
            cleaned[str(k)] = _scrub_sensitive(v)
        return cleaned
    if isinstance(value, list):
        return [_scrub_sensitive(item) for item in value]
    return value


def _cap_output_size(payload: Any) -> Any:
    """控制写入 metadata.output 的整体大小，避免 ES 字段爆掉。"""
    try:
        import json as _json
        text = _json.dumps(payload, ensure_ascii=False, default=str)
    except TypeError:
        return payload
    if len(text) <= _MAX_OUTPUT_TOTAL_LEN:
        return payload
    # 超长时整体降级为摘要：保留 keys 列表和截断字符串
    if isinstance(payload, dict):
        return {
            "_truncated": True,
            "_original_keys": list(payload.keys())[:20],
            "_truncated_at_chars": _MAX_OUTPUT_TOTAL_LEN,
        }
    return _truncate(payload, _MAX_OUTPUT_TOTAL_LEN)


def _extract_llm_call_output(call: dict[str, Any]) -> tuple[dict | None, bool]:
    """从 LLM Call 记录中提取可作为待评测 output 的字段。

    返回 (output, missing)。
    """
    # 优先级从高到低
    candidate_keys = (
        "output",
        "response",
        "response_text",
        "completion",
        "content",
        "result",
        "final_output",
    )
    raw: Any = None
    for key in candidate_keys:
        if key in call and call[key] is not None:
            raw = call[key]
            break
    if raw is None:
        # 有些 provider 把 content 放在 metadata / output_payload 下
        for nested_key in ("metadata", "payload"):
            nested = call.get(nested_key)
            if isinstance(nested, dict):
                for key in candidate_keys:
                    if key in nested and nested[key] is not None:
                        raw = nested[key]
                        break
            if raw is not None:
                break

    if raw is None:
        return None, True

    if not isinstance(raw, dict):
        # 单字符串 / 列表等尽量包装成 dict 让 static eval 能识别
        scrubbed = _scrub_sensitive({"text": _truncate(raw)})
        return _cap_output_size(scrubbed), False

    scrubbed = _scrub_sensitive(raw)
    # 限制单字段长度
    if isinstance(scrubbed, dict):
        scrubbed = {k: _truncate(v) for k, v in scrubbed.items()}
    return _cap_output_size(scrubbed), False


def _extract_node_trace_output(node_trace: dict[str, Any]) -> tuple[dict | None, bool]:
    """从 node_trace 中提取节点输出。"""
    candidate_keys = (
        "output",
        "final_output",
        "result",
        "response",
        "node_output",
        "llm_output",
    )
    raw: Any = None
    for key in candidate_keys:
        if key in node_trace and node_trace[key] is not None:
            raw = node_trace[key]
            break
    if raw is None:
        # 兜底：嵌套 fields
        for nested_key in ("fields", "payload", "data"):
            nested = node_trace.get(nested_key)
            if isinstance(nested, dict):
                for key in candidate_keys:
                    if key in nested and nested[key] is not None:
                        raw = nested[key]
                        break
            if raw is not None:
                break

    if raw is None:
        return None, True

    if not isinstance(raw, dict):
        scrubbed = _scrub_sensitive({"text": _truncate(raw)})
        return _cap_output_size(scrubbed), False

    scrubbed = _scrub_sensitive(raw)
    if isinstance(scrubbed, dict):
        scrubbed = {k: _truncate(v) for k, v in scrubbed.items()}
    return _cap_output_size(scrubbed), False


def _summarize_messages(call: dict[str, Any]) -> dict[str, Any]:
    """构造不含敏感原始 prompt 内容的 messages 摘要。

    永远不复制完整 prompt / messages 内容到 case input。
    """
    messages = call.get("messages")
    if isinstance(messages, list):
        roles = sorted({str(m.get("role")) for m in messages if isinstance(m, dict) and m.get("role")})
        return {
            "messages_role_count": len(messages),
            "messages_roles": roles,
        }
    return {"messages_role_count": 0, "messages_roles": []}


def build_node_eval_case_from_llm_call(
    call: dict[str, Any],
    *,
    save: bool = False,
) -> EvalCase:
    call_id = str(call.get("call_id") or "")
    if not call_id:
        raise ValueError("LLM call is missing call_id")
    node_name = call.get("node_name")
    if not node_name:
        raise ValueError("LLM call is missing node_name; cannot create node eval case")
    agent_name = str(call.get("agent_name") or "unknown")
    run_id = call.get("run_id")
    prompt_key = call.get("prompt_key")
    prompt_version = call.get("prompt_version")
    prompt_hash = call.get("prompt_hash")
    model = call.get("model")
    call_type = call.get("call_type")
    now = utc_now_iso()
    # 不保存原始 prompt / messages 内容，避免敏感账户数据落到 eval case。
    # 用户可在 EvalCaseEditorDialog 中编辑 input 摘要。
    input_payload: dict[str, Any] = {
        "source_call_id": call_id,
        "node_input_present": bool(call.get("prompt") or call.get("messages") or call.get("input")),
        "note": "原始输入请查看 source llm call",
    }

    output, output_missing = _extract_llm_call_output(call)
    metadata: dict[str, Any] = {
        "source_type": "llm_call",
        "source_run_id": run_id,
        "source_llm_call_id": call_id,
        "node_name": node_name,
        "prompt_key": prompt_key,
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash,
        "model": model,
        "call_type": call_type,
        "created_from_trace_at": now,
    }
    if output is not None:
        metadata["output"] = output
    if output_missing:
        metadata["output_missing"] = True

    return EvalCase(
        case_id=new_eval_case_id(agent_name),
        agent_name=agent_name,
        title=f"Node Eval - {agent_name} / {node_name}",
        description=f"Auto-generated from LLM call {call_id}",
        tags=["node_eval", str(node_name)],
        source="llm_call",
        enabled=False,
        severity="medium",
        category="node_quality",
        input=input_payload,
        mock_context={},
        mock_tool_outputs={},
        expected_behavior=_default_expected_behavior(str(node_name)),
        expected_output_fields=[],
        forbidden_behavior=[],
        scoring_rubric={},
        metadata=metadata,
        eval_scope="node",
        node_name=str(node_name),
        source_run_id=run_id,
        source_llm_call_id=call_id,
        source_node_trace_id=None,
        prompt_key=prompt_key,
        prompt_version=prompt_version,
        prompt_hash=prompt_hash,
        model=model,
    )


def _node_trace_id(node_trace: dict[str, Any], index: int) -> str:
    return str(
        node_trace.get("trace_id")
        or node_trace.get("node_trace_id")
        or node_trace.get("id")
        or f"index_{index}"
    )


def _normalize_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = float(text)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _normalize_node_latency_ms(node_trace: dict[str, Any]) -> int | float | None:
    candidate_keys = ("latency_ms", "elapsed_ms", "duration_ms", "latency", "elapsed")
    containers: list[dict[str, Any]] = [node_trace]
    for nested_key in ("fields", "payload", "data"):
        nested = node_trace.get(nested_key)
        if isinstance(nested, dict):
            containers.append(nested)
    for key in candidate_keys:
        for container in containers:
            if key in container:
                normalized = _normalize_number(container.get(key))
                if normalized is not None:
                    return normalized
    return None


def build_node_eval_case_from_node_trace(
    run: dict[str, Any],
    node_trace: dict[str, Any],
    *,
    node_trace_id: str | None = None,
    index: int = 0,
) -> EvalCase:
    run_id = str(run.get("run_id") or "")
    if not run_id:
        raise ValueError("Agent run is missing run_id; cannot create node eval case")
    actual_id = node_trace_id or _node_trace_id(node_trace, index)
    node_name = node_trace.get("node_name")
    if not node_name:
        raise ValueError(f"node_trace {actual_id} is missing node_name; cannot create node eval case")
    agent_name = str(run.get("agent_name") or "unknown")
    now = utc_now_iso()

    output, output_missing = _extract_node_trace_output(node_trace)
    metadata: dict[str, Any] = {
        "source_type": "node_trace",
        "source_run_id": run_id,
        "source_node_trace_id": actual_id,
        "node_name": node_name,
        "node_status": node_trace.get("status"),
        "node_latency_ms": _normalize_node_latency_ms(node_trace),
        "created_from_trace_at": now,
    }
    if output is not None:
        metadata["output"] = output
    if output_missing:
        metadata["output_missing"] = True

    return EvalCase(
        case_id=new_eval_case_id(agent_name),
        agent_name=agent_name,
        title=f"Node Eval - {agent_name} / {node_name}",
        description=f"Auto-generated from node trace {actual_id} of run {run_id}",
        tags=["node_eval", str(node_name)],
        source="node_trace",
        enabled=False,
        severity="medium",
        category="node_quality",
        input={
            "source_run_id": run_id,
            "source_node_trace_id": actual_id,
            "note": "原始输入请查看 source node trace",
        },
        mock_context={},
        mock_tool_outputs={},
        expected_behavior=_default_expected_behavior(str(node_name)),
        expected_output_fields=[],
        forbidden_behavior=[],
        scoring_rubric={},
        metadata=metadata,
        eval_scope="node",
        node_name=str(node_name),
        source_run_id=run_id,
        source_llm_call_id=None,
        source_node_trace_id=actual_id,
    )


def find_node_trace_by_id(
    run: dict[str, Any], node_trace_id: str
) -> tuple[dict | None, int]:
    traces = run.get("node_traces") or []
    if not isinstance(traces, list):
        return None, -1
    for idx, trace in enumerate(traces):
        if not isinstance(trace, dict):
            continue
        actual = (
            trace.get("trace_id")
            or trace.get("node_trace_id")
            or trace.get("id")
            or f"index_{idx}"
        )
        if str(actual) == node_trace_id:
            return trace, idx
    return None, -1
