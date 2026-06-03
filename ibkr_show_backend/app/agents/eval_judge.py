"""LLM-as-Judge evaluation service."""

from __future__ import annotations

import json
from typing import Any, Protocol

from app.agents.eval_correctness_rubrics import (
    ACCOUNT_COPILOT_RUBRIC,
    DAILY_POSITION_REVIEW_RUBRIC,
    GLOBAL_CORRECTNESS_DIMENSIONS,
    TRADE_DECISION_RUBRIC,
    TRADE_REVIEW_RUBRIC,
    get_agent_type,
)


class JudgeLLMClient(Protocol):
    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> str: ...


DEFAULT_JUDGE_RUBRIC = {
    "answer_relevance": {
        "max_score": 20,
        "description": "是否直接回答用户问题，是否没有跑题",
    },
    "grounding": {
        "max_score": 20,
        "description": "结论是否基于提供的账户、行情、工具或上下文信息，是否避免无依据臆测",
    },
    "risk_awareness": {
        "max_score": 20,
        "description": "是否充分说明投资风险、数据限制和不确定性",
    },
    "actionability": {
        "max_score": 20,
        "description": "建议是否可执行，是否给出条件、仓位、观察点或下一步",
    },
    "no_overclaiming": {
        "max_score": 20,
        "description": "是否避免稳赚、必涨、无风险、确定性收益等过度承诺",
    },
}


# Eval P3 Stage 06: 统一 Judge Rubric / 维度定义
AGENT_RUBRIC_REGISTRY: dict[str, dict[str, dict[str, Any]]] = {
    "trade_decision": TRADE_DECISION_RUBRIC,
    "daily_position_review": DAILY_POSITION_REVIEW_RUBRIC,
    "trade_review": TRADE_REVIEW_RUBRIC,
    "account_copilot": ACCOUNT_COPILOT_RUBRIC,
}


def get_rubric_for_agent(agent_name: str) -> dict[str, dict[str, Any]]:
    """返回该 Agent 的专属 rubric；未知 agent 返回空 dict（只用 global 维度）。"""
    if not agent_name:
        return {}
    return AGENT_RUBRIC_REGISTRY.get(agent_name, {})


def _truncate(text: str, max_len: int = 4000) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


def _format_dimensions(dimensions: dict[str, dict[str, Any]]) -> str:
    """格式化维度描述为 markdown 列表。"""
    if not dimensions:
        return "- （无）"
    lines = []
    for dim_id, info in dimensions.items():
        title = info.get("title", dim_id)
        desc = info.get("description", "")
        severity = info.get("severity", "")
        lines.append(f"- **{dim_id}** ({title}, severity={severity}): {desc}")
    return "\n".join(lines)


def build_correctness_judge_prompt(
    *,
    agent_name: str,
    eval_scope: str = "agent",
    node_name: str | None = None,
    case: dict,
    output: dict | str,
) -> str:
    """Eval P3 Stage 06: 统一 Judge Prompt Builder。

    返回 user prompt（system prompt 单独由调用方拼接）。
    包含：
    - agent_name / agent_type
    - global correctness dimensions
    - agent-specific rubric
    - node-specific rubric（如果有）
    - case expected_behavior / forbidden_behavior
    - output to judge
    - JSON output schema
    """
    case = case if isinstance(case, dict) else {}
    input_data = case.get("input") or {}
    expected_behavior = case.get("expected_behavior") or {}
    forbidden = case.get("forbidden_behavior") or []
    expected_dl = case.get("expected_data_limitations") or []
    case_title = case.get("title", "")
    case_description = case.get("description", "") or ""

    agent_type = get_agent_type(agent_name)
    agent_rubric = get_rubric_for_agent(agent_name)
    global_dims = GLOBAL_CORRECTNESS_DIMENSIONS

    # Node rubric：trade_decision 的各节点 rubric
    node_rubric_section = ""
    if eval_scope == "node" and node_name and agent_name == "trade_decision":
        node_rubric_section = f"\n## 节点 {node_name} 的特定关注\n- 关注该节点是否输出该有的关键字段。\n- 检查点可参考 trade_decision node 评测的现有规则。\n"

    if isinstance(output, dict):
        output_text = json.dumps(output, ensure_ascii=False, indent=2)
    else:
        output_text = str(output)

    prompt = f"""请对以下 Agent 输出进行 correctness 评测。

## Agent 信息
- agent_name: {agent_name}
- agent_type: {agent_type}
- eval_scope: {eval_scope}
- node_name: {node_name or '(none)'}

## Case 概况
- case_title: {case_title}
- case_description: {_truncate(case_description, 500)}

## 全局正确性维度（适用于所有 Agent）
{_format_dimensions(global_dims)}

## Agent 专属 Rubric（{agent_name}）
{_format_dimensions(agent_rubric)}
{node_rubric_section}

## 用户输入
{_truncate(json.dumps(input_data, ensure_ascii=False, indent=2), 2000)}

## 期望行为
{_truncate(json.dumps(expected_behavior, ensure_ascii=False, indent=2), 1000)}

## 禁止行为
{json.dumps(forbidden, ensure_ascii=False)}

## 期望数据限制声明
{json.dumps(expected_dl, ensure_ascii=False)}

## Agent 输出
{_truncate(output_text, 4000)}

## JSON 输出 Schema（必须严格遵守）
{{
  "passed": true,
  "overall_score": 0.82,
  "dimension_scores": {{
    "{list(global_dims.keys())[0]}": 0.9,
    "{list(agent_rubric.keys())[0] if agent_rubric else list(global_dims.keys())[1]}": 0.8
  }},
  "failed_dimensions": [],
  "warnings": [],
  "failure_reasons": [],
  "confidence": 0.8
}}

要求：
1. passed: 严格基于 evidence。
2. overall_score: 0~1 之间。
3. dimension_scores: 至少包含上文中提到的所有相关维度，每项 0~1。
4. failed_dimensions: dimension_scores < 0.6 的维度名。
5. failure_reasons: 失败的具体原因（短字符串数组）。
6. warnings: 警告但未失败的维度（短字符串数组）。
7. confidence: 0~1，你对判断的把握。
8. 只输出 JSON，不要 markdown 包裹，不要解释。
"""
    return prompt


CORRECTNESS_JUDGE_SYSTEM_PROMPT = (
    "你是一个严格的 AI 输出质量评测裁判，专门评估本项目 Agent 输出是否符合 correctness 标准。"
    "你必须基于提供的 input、context、case、output 做出判断。"
    "你不能因为自己不同意投资方向就判失败。"
    "你必须使用 0~1 的小数打分；0.6 以下视为该维度失败。"
    "你必须严格按 JSON Schema 输出，不要包裹 markdown。"
)


def _build_correctness_judge_messages(
    agent_name: str,
    eval_scope: str,
    node_name: str | None,
    case: dict,
    output: dict | str,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": CORRECTNESS_JUDGE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_correctness_judge_prompt(
                agent_name=agent_name,
                eval_scope=eval_scope,
                node_name=node_name,
                case=case,
                output=output,
            ),
        },
    ]


def _build_judge_messages(case: dict, output: dict, rubric: dict) -> list[dict[str, str]]:
    input_data = case.get("input") or {}
    expected_behavior = case.get("expected_behavior") or {}
    forbidden = case.get("forbidden_behavior") or []
    expected_dl = case.get("expected_data_limitations") or []

    rubric_text = "\n".join(
        f"- {dim}: {info.get('description', '')} (max {info.get('max_score', 20)}分)"
        for dim, info in rubric.items()
    )

    user_content = f"""请评测以下 Agent 输出的质量。

## 评测维度
{rubric_text}

## Agent 信息
- agent_name: {case.get('agent_name', 'unknown')}
- case_title: {case.get('title', '')}
- case_description: {_truncate(case.get('description', '') or '', 500)}

## 用户输入
{_truncate(json.dumps(input_data, ensure_ascii=False, indent=2), 2000)}

## 期望行为
{_truncate(json.dumps(expected_behavior, ensure_ascii=False, indent=2), 1000)}

## 禁止行为
{json.dumps(forbidden, ensure_ascii=False)}

## 期望数据限制声明
{json.dumps(expected_dl, ensure_ascii=False)}

## Agent 输出
{_truncate(json.dumps(output, ensure_ascii=False, indent=2), 4000)}

请严格以 JSON 格式输出评测结果，包含以下字段：
- overall_score: 总分 (0-100)
- passed: boolean，是否通过
- confidence: "high" / "medium" / "low"
- dimensions: 对象，每个维度包含 score, max_score, reason
- major_issues: 字符串数组，主要问题
- minor_issues: 字符串数组，次要问题
- verdict: "pass" / "fail" / "warning"

只输出 JSON，不要输出其他内容。"""

    return [
        {
            "role": "system",
            "content": (
                "你是一个严格的 AI 输出质量评测裁判。你的职责是评估 Agent 输出的质量，而不是生成投资建议。"
                "你必须基于提供的 input、context 和 output 进行评测。"
                "你不能因为自己不同意投资方向就判失败。"
                "重点判断输出是否合理、审慎、基于证据、没有过度承诺。"
                "你必须输出 JSON 格式的评测结果。"
            ),
        },
        {"role": "user", "content": user_content},
    ]


def _parse_judge_output(raw: str) -> dict:
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
    return {}


def _coerce_0_1(value: Any) -> float:
    """把任意数值归一化到 0~1。"""
    if not isinstance(value, (int, float)):
        return 0.0
    if value > 1.0:
        # 0~100 分数归一化
        return max(0.0, min(1.0, float(value) / 100.0))
    return max(0.0, min(1.0, float(value)))


def normalize_correctness_judge_result(parsed: dict, expected_dimensions: list[str] | None = None) -> dict:
    """Eval P3 Stage 06: 把 Judge JSON 归一化成统一结构。

    输入：parse_judge_output 返回的 dict
    输出：{
      "passed": bool,
      "overall_score": 0~1,
      "dimension_scores": dict[str, 0~1],
      "failed_dimensions": list[str],
      "warnings": list[str],
      "failure_reasons": list[str],
      "confidence": 0~1,
    }

    缺字段补默认值；分数超过 0~1 归一化；failed_dimensions 为空但分数 < 0.6 时自动补充。
    """
    if not isinstance(parsed, dict):
        parsed = {}
    overall_score = _coerce_0_1(parsed.get("overall_score"))
    passed = parsed.get("passed")
    if not isinstance(passed, bool):
        passed = overall_score >= 0.6

    dim_scores_in = parsed.get("dimension_scores") or parsed.get("dimensions") or {}
    dimension_scores: dict[str, float] = {}
    if isinstance(dim_scores_in, dict):
        for k, v in dim_scores_in.items():
            if isinstance(v, dict):
                # legacy {"score": 0~1, "max_score": 20, "reason": "..."} 或 {"score": 0~100}
                score = v.get("score")
                if score is None:
                    continue
                dimension_scores[str(k)] = _coerce_0_1(score)
            elif isinstance(v, (int, float)):
                dimension_scores[str(k)] = _coerce_0_1(v)

    # 补默认值
    if expected_dimensions:
        for dim in expected_dimensions:
            dimension_scores.setdefault(dim, 0.0)

    failed_dimensions_in = parsed.get("failed_dimensions")
    failed_dimensions: list[str] = []
    if isinstance(failed_dimensions_in, list):
        failed_dimensions = [str(d) for d in failed_dimensions_in if d]
    # 缺字段但分数 < 0.6 自动补充
    for dim, score in dimension_scores.items():
        if score < 0.6 and dim not in failed_dimensions:
            failed_dimensions.append(dim)

    warnings_in = parsed.get("warnings")
    if not isinstance(warnings_in, list):
        warnings_in = []
    warnings = [str(w) for w in warnings_in if w]

    failure_reasons_in = parsed.get("failure_reasons")
    if not isinstance(failure_reasons_in, list):
        failure_reasons_in = []
    failure_reasons = [str(r) for r in failure_reasons_in if r]

    confidence = _coerce_0_1(parsed.get("confidence"))

    return {
        "passed": bool(passed),
        "overall_score": float(overall_score),
        "dimension_scores": dimension_scores,
        "failed_dimensions": failed_dimensions,
        "warnings": warnings,
        "failure_reasons": failure_reasons,
        "confidence": float(confidence),
    }


def _validate_judge_result(parsed: dict, rubric: dict) -> dict:
    overall_score = parsed.get("overall_score")
    if not isinstance(overall_score, (int, float)):
        overall_score = 0
    overall_score = max(0, min(100, float(overall_score)))

    passed = parsed.get("passed")
    if not isinstance(passed, bool):
        passed = overall_score >= 60

    dimensions = parsed.get("dimensions")
    if not isinstance(dimensions, dict):
        dimensions = {}
    for dim_name, dim_info in rubric.items():
        if dim_name not in dimensions:
            dimensions[dim_name] = {"score": 0, "max_score": dim_info.get("max_score", 20), "reason": "judge 未返回该维度"}

    major_issues = parsed.get("major_issues")
    if not isinstance(major_issues, list):
        major_issues = []

    minor_issues = parsed.get("minor_issues")
    if not isinstance(minor_issues, list):
        minor_issues = []

    verdict = parsed.get("verdict")
    if verdict not in ("pass", "fail", "warning"):
        verdict = "pass" if passed else "fail"

    confidence = parsed.get("confidence")
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    return {
        "overall_score": overall_score,
        "passed": passed,
        "confidence": confidence,
        "dimensions": dimensions,
        "major_issues": major_issues,
        "minor_issues": minor_issues,
        "verdict": verdict,
    }


class AgentEvalJudgeService:
    def __init__(self, llm_client: Any = None) -> None:
        self.llm_client = llm_client

    def judge(
        self,
        *,
        case: dict,
        output: dict,
        eval_mode: str = "static",
    ) -> dict:
        if self.llm_client is None:
            return {
                "ok": False,
                "score": 0,
                "max_score": 100,
                "passed": False,
                "verdict": "fail",
                "raw": {},
                "error_code": "LLM_JUDGE_SERVICE_UNAVAILABLE",
                "error_message": "No LLM client available for judge",
            }

        rubric = case.get("judge_rubric") or {}
        if not rubric:
            rubric = DEFAULT_JUDGE_RUBRIC

        messages = _build_judge_messages(case, output, rubric)
        try:
            if hasattr(self.llm_client, "chat_with_metadata"):
                result = self.llm_client.chat_with_metadata(
                    messages,
                    call_type="eval_judge",
                    agent_name="eval_judge",
                    node_name="llm_judge",
                    prompt_metadata={
                        "case_id": case.get("case_id"),
                        "agent_name": case.get("agent_name"),
                        "eval_mode": eval_mode,
                        "judge_enabled": True,
                    },
                )
                raw_output = result.content if hasattr(result, "content") else str(result)
            else:
                raw_output = self.llm_client.chat(messages)
        except Exception as exc:
            return {
                "ok": False,
                "score": 0,
                "max_score": 100,
                "passed": False,
                "verdict": "fail",
                "raw": {},
                "error_code": "LLM_JUDGE_CALL_FAILED",
                "error_message": str(exc)[:500],
            }

        parsed = _parse_judge_output(raw_output)
        if not parsed:
            return {
                "ok": False,
                "score": 0,
                "max_score": 100,
                "passed": False,
                "verdict": "fail",
                "raw": {"raw_output": raw_output[:1000]},
                "error_code": "LLM_JUDGE_PARSE_FAILED",
                "error_message": "Failed to parse judge output as JSON",
            }

        validated = _validate_judge_result(parsed, rubric)
        return {
            "ok": True,
            "score": validated["overall_score"],
            "max_score": 100,
            "passed": validated["passed"],
            "verdict": validated["verdict"],
            "raw": validated,
            "error_code": None,
            "error_message": None,
        }

    def judge_correctness(
        self,
        *,
        case: dict,
        output: dict,
        eval_scope: str = "agent",
        node_name: str | None = None,
        eval_mode: str = "static",
    ) -> dict:
        """Eval P3 Stage 06: 用统一 correctness rubric 评测一个 case 的输出。

        返回的 raw 字段符合 Stage 06 规范：
        - passed: bool
        - overall_score: 0~1
        - dimension_scores: dict[str, 0~1]
        - failed_dimensions / warnings / failure_reasons: list[str]
        - confidence: 0~1
        """
        agent_name = str(case.get("agent_name", "unknown") or "unknown")
        # 决定 expected_dimensions：global + 该 agent 专属
        from app.agents.eval_correctness_rubrics import (
            get_dimensions_for_agent,
        )
        expected_dims = [d["dimension"] for d in get_dimensions_for_agent(agent_name)]

        if self.llm_client is None:
            return {
                "ok": False,
                "score": 0.0,
                "max_score": 1.0,
                "passed": False,
                "verdict": "fail",
                "raw": {
                    "passed": False,
                    "overall_score": 0.0,
                    "dimension_scores": {dim: 0.0 for dim in expected_dims},
                    "failed_dimensions": list(expected_dims),
                    "warnings": [],
                    "failure_reasons": ["LLM_JUDGE_SERVICE_UNAVAILABLE"],
                    "confidence": 0.0,
                },
                "error_code": "LLM_JUDGE_SERVICE_UNAVAILABLE",
                "error_message": "No LLM client available for judge",
            }

        messages = _build_correctness_judge_messages(
            agent_name=agent_name,
            eval_scope=eval_scope,
            node_name=node_name,
            case=case,
            output=output,
        )
        try:
            if hasattr(self.llm_client, "chat_with_metadata"):
                result = self.llm_client.chat_with_metadata(
                    messages,
                    call_type="eval_judge_correctness",
                    agent_name="eval_judge",
                    node_name="llm_judge_correctness",
                    prompt_metadata={
                        "case_id": case.get("case_id"),
                        "agent_name": agent_name,
                        "eval_mode": eval_mode,
                        "judge_enabled": True,
                        "judge_kind": "correctness",
                    },
                )
                raw_output = result.content if hasattr(result, "content") else str(result)
            else:
                raw_output = self.llm_client.chat(messages)
        except Exception as exc:
            return {
                "ok": False,
                "score": 0.0,
                "max_score": 1.0,
                "passed": False,
                "verdict": "fail",
                "raw": {
                    "passed": False,
                    "overall_score": 0.0,
                    "dimension_scores": {dim: 0.0 for dim in expected_dims},
                    "failed_dimensions": list(expected_dims),
                    "warnings": [],
                    "failure_reasons": [f"LLM_JUDGE_CALL_FAILED: {str(exc)[:200]}"],
                    "confidence": 0.0,
                },
                "error_code": "LLM_JUDGE_CALL_FAILED",
                "error_message": str(exc)[:500],
            }

        parsed = _parse_judge_output(raw_output)
        if not parsed:
            return {
                "ok": False,
                "score": 0.0,
                "max_score": 1.0,
                "passed": False,
                "verdict": "fail",
                "raw": {
                    "passed": False,
                    "overall_score": 0.0,
                    "dimension_scores": {dim: 0.0 for dim in expected_dims},
                    "failed_dimensions": list(expected_dims),
                    "warnings": [],
                    "failure_reasons": ["LLM_JUDGE_PARSE_FAILED"],
                    "confidence": 0.0,
                },
                "error_code": "LLM_JUDGE_PARSE_FAILED",
                "error_message": "Failed to parse judge output as JSON",
                "raw_output": raw_output[:1000],
            }

        normalized = normalize_correctness_judge_result(parsed, expected_dimensions=expected_dims)
        return {
            "ok": True,
            "score": normalized["overall_score"],
            "max_score": 1.0,
            "passed": normalized["passed"],
            "verdict": "pass" if normalized["passed"] else "fail",
            "raw": normalized,
            "error_code": None,
            "error_message": None,
        }
