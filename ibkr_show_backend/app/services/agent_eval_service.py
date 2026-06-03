from __future__ import annotations

from typing import Any

from app.agents.eval_cases import list_builtin_eval_cases
from app.agents.eval_checks import run_eval_checks
from app.agents.eval_harness import (
    BadCaseFeedback,
    CheckResult,
    EvalCase,
    EvalCaseResult,
    EvalRun,
    VALID_FEEDBACK_CATEGORIES,
    VALID_FEEDBACK_ISSUE_TYPES,
    VALID_FEEDBACK_STATUSES,
    build_eval_case_from_replay,
    new_eval_case_id,
    new_eval_run_id,
    new_feedback_id,
    utc_now_iso,
)
from app.agents.eval_judge import AgentEvalJudgeService
from app.agents.eval_live_mock import LiveMockEvalExecutor
from app.agents.eval_node_case_builder import (
    build_node_eval_case_from_llm_call,
    build_node_eval_case_from_node_trace,
    find_node_trace_by_id,
)
from app.services.agent_eval_repository import BadCaseFeedbackRepository, EvalCaseRepository, EvalRunRepository
from app.services.agent_replay_service import AgentReplayService

_SEVERITY_VALUES = {"low", "medium", "high", "critical"}

_DEFAULT_GATE = {
    "fail_on_critical": True,
    "fail_on_high": False,
    "min_pass_rate": 0.9,
    "max_failed": None,
}


def _case_is_enabled(case: dict) -> bool:
    return case.get("enabled", True) is not False


def _case_is_archived(case: dict) -> bool:
    return case.get("archived", False) is True


def _evaluate_gate_dict(summary: dict, gate: dict) -> dict:
    reasons: list[str] = []
    pass_rate = summary.get("pass_rate", 0)
    critical_count = summary.get("critical_failure_count", 0)
    high_count = summary.get("high_priority_failure_count", 0)
    failed_count = summary.get("failed_count", 0) + summary.get("error_count", 0)

    if gate.get("fail_on_critical") and critical_count > 0:
        reasons.append(f"critical_failure_count {critical_count} > 0")
    if gate.get("fail_on_high") and high_count > 0:
        reasons.append(f"high_priority_failure_count {high_count} > 0")
    if gate.get("max_failed") is not None and failed_count > gate["max_failed"]:
        reasons.append(f"failed_count {failed_count} > max_failed {gate['max_failed']}")
    min_rate = gate.get("min_pass_rate")
    if min_rate is not None and pass_rate < min_rate:
        reasons.append(f"pass_rate {pass_rate:.3f} < required {min_rate}")

    return {
        "passed": len(reasons) == 0,
        "reasons": reasons,
        "critical_failure_count": critical_count,
        "high_priority_failure_count": high_count,
        "failed_count": summary.get("failed_count", 0),
        "error_count": summary.get("error_count", 0),
        "pass_rate": pass_rate,
        "min_pass_rate": min_rate,
    }


def _build_scope_breakdown(results: list[dict]) -> dict[str, dict[str, Any]]:
    """根据 result.metadata.eval_scope 聚合 agent / node 两个维度的统计。

    failed_count 包含 result.status == failed 的 result。
    注意 result.status 的 failed 已经把 fatal / critical / high severity 检查
    失败视为 failed（见 _evaluate_case）。
    """
    buckets: dict[str, dict[str, Any]] = {
        "agent": {"case_count": 0, "passed_count": 0, "failed_count": 0, "error_count": 0, "warning_count": 0},
        "node": {"case_count": 0, "passed_count": 0, "failed_count": 0, "error_count": 0, "warning_count": 0},
    }
    for result in results:
        meta = result.get("metadata") or {}
        scope = meta.get("eval_scope") or "agent"
        if scope not in buckets:
            scope = "agent"
        bucket = buckets[scope]
        bucket["case_count"] += 1
        status = result.get("status") or ""
        if status == "passed":
            bucket["passed_count"] += 1
        elif status == "failed":
            bucket["failed_count"] += 1
        elif status == "error":
            bucket["error_count"] += 1
        elif status == "warning":
            bucket["warning_count"] += 1

    for scope, bucket in buckets.items():
        count = bucket["case_count"]
        bucket["pass_rate"] = (bucket["passed_count"] / count) if count else None

    has_node = any(b["case_count"] for b in buckets.values()) and buckets["node"]["case_count"] > 0
    has_agent = buckets["agent"]["case_count"] > 0
    return {
        **buckets,
        "mixed": has_node and has_agent,
    }


class AgentEvalService:
    def __init__(
        self,
        case_repository: EvalCaseRepository,
        run_repository: EvalRunRepository,
        replay_service: AgentReplayService | None = None,
        llm_client: object | None = None,
        judge_service: AgentEvalJudgeService | None = None,
        feedback_repository: BadCaseFeedbackRepository | None = None,
        llm_call_service: object | None = None,
        run_trace_repository: object | None = None,
    ) -> None:
        self.case_repository = case_repository
        self.run_repository = run_repository
        self.replay_service = replay_service
        self.live_mock_executor = LiveMockEvalExecutor(llm_client=llm_client)
        self.judge_service = judge_service or AgentEvalJudgeService(llm_client=llm_client)
        self.feedback_repository = feedback_repository
        self.llm_call_service = llm_call_service
        self.run_trace_repository = run_trace_repository

    def list_cases(
        self,
        *,
        agent_name: str | None = None,
        source: str | None = None,
        enabled: bool | None = None,
        severity: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        source_replay_id: str | None = None,
        eval_scope: str | None = None,
        node_name: str | None = None,
        source_run_id: str | None = None,
        source_llm_call_id: str | None = None,
        prompt_key: str | None = None,
        model: str | None = None,
        include_archived: bool = False,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        stored = self.case_repository.list_cases(
            agent_name=agent_name, source=source, enabled=enabled,
            severity=severity, category=category, tag=tag,
            source_replay_id=source_replay_id,
            eval_scope=eval_scope, node_name=node_name,
            source_run_id=source_run_id, source_llm_call_id=source_llm_call_id,
            prompt_key=prompt_key, model=model,
            include_archived=include_archived,
            query=query, limit=limit,
        )
        if stored:
            return stored
        cases = [case.to_dict() for case in list_builtin_eval_cases()]
        if agent_name:
            cases = [c for c in cases if c.get("agent_name") == agent_name]
        if source:
            cases = [c for c in cases if c.get("source") == source]
        if enabled is not None:
            cases = [c for c in cases if _case_is_enabled(c) is enabled]
        if not include_archived:
            cases = [c for c in cases if not _case_is_archived(c)]
        if severity:
            cases = [c for c in cases if c.get("severity", "medium") == severity]
        if category:
            cases = [c for c in cases if c.get("category", "") == category]
        if tag:
            cases = [c for c in cases if tag in (c.get("tags") or [])]
        if source_replay_id:
            cases = [c for c in cases if c.get("source_replay_id") == source_replay_id]
        if eval_scope:
            cases = [c for c in cases if c.get("eval_scope", "agent") == eval_scope]
        if node_name:
            cases = [c for c in cases if c.get("node_name") == node_name]
        if source_run_id:
            cases = [c for c in cases if c.get("source_run_id") == source_run_id]
        if source_llm_call_id:
            cases = [c for c in cases if c.get("source_llm_call_id") == source_llm_call_id]
        if prompt_key:
            cases = [c for c in cases if c.get("prompt_key") == prompt_key]
        if model:
            cases = [c for c in cases if c.get("model") == model]
        if query:
            q = query.lower()
            cases = [c for c in cases if q in (c.get("title") or "").lower() or q in (c.get("case_id") or "").lower() or q in (c.get("description") or "").lower() or q in (c.get("notes") or "").lower()]
        return cases[:limit]

    def get_case(self, case_id: str) -> dict | None:
        stored = self.case_repository.get_case(case_id)
        if stored:
            return stored
        return next((case.to_dict() for case in list_builtin_eval_cases() if case.case_id == case_id), None)

    def create_case(self, payload: dict) -> dict:
        if not payload.get("case_id"):
            payload["case_id"] = new_eval_case_id(payload.get("agent_name", "unknown"))
        case = EvalCase.from_dict(payload)
        return self.case_repository.save_case(case.to_dict())

    def update_case(self, case_id: str, updates: dict) -> dict | None:
        existing = self.get_case(case_id)
        if existing is None:
            return None
        allowed = {
            "title", "description", "tags", "enabled", "severity", "category",
            "input", "mock_context", "mock_tool_outputs", "expected_behavior",
            "expected_output_fields", "expected_tools", "expected_data_limitations",
            "forbidden_behavior", "scoring_rubric", "notes", "metadata",
            "judge_enabled", "judge_rubric", "judge_model_config",
            "eval_scope", "node_name", "source_run_id", "source_llm_call_id",
            "source_node_trace_id", "prompt_key", "prompt_version", "prompt_hash",
            "model",
        }
        merged = dict(existing)
        for key, value in updates.items():
            if key in allowed:
                merged[key] = value
        if "severity" in updates and updates["severity"] not in _SEVERITY_VALUES:
            raise ValueError(f"Invalid severity: {updates['severity']}")
        merged["updated_at"] = utc_now_iso()
        case = EvalCase.from_dict(merged)
        return self.case_repository.save_case(case.to_dict())

    def archive_case(self, case_id: str, *, reason: str | None = None) -> dict | None:
        existing = self.get_case(case_id)
        if existing is None:
            return None
        now = utc_now_iso()
        merged = dict(existing)
        merged["archived"] = True
        merged["archived_at"] = now
        merged["archived_reason"] = reason
        merged["enabled"] = False
        merged["updated_at"] = now
        case = EvalCase.from_dict(merged)
        return self.case_repository.save_case(case.to_dict())

    def unarchive_case(self, case_id: str) -> dict | None:
        existing = self.get_case(case_id)
        if existing is None:
            return None
        merged = dict(existing)
        merged["archived"] = False
        merged["archived_at"] = None
        merged["archived_reason"] = None
        merged["updated_at"] = utc_now_iso()
        case = EvalCase.from_dict(merged)
        return self.case_repository.save_case(case.to_dict())

    def bulk_update_cases(self, case_ids: list[str], updates: dict) -> dict:
        if not case_ids:
            return {"updated_count": 0, "failed_count": 0, "items": []}
        severity = updates.get("severity")
        if severity is not None and severity not in _SEVERITY_VALUES:
            raise ValueError(f"Invalid severity: {severity}")
        tags_add = [t.strip() for t in (updates.get("tags_add") or []) if t.strip()]
        tags_remove = set(t.strip() for t in (updates.get("tags_remove") or []) if t.strip())
        notes_append = (updates.get("notes_append") or "").strip()

        items = []
        updated_count = 0
        for case_id in case_ids:
            existing = self.get_case(case_id)
            if existing is None:
                items.append({"case_id": case_id, "status": "error", "error_code": "CASE_NOT_FOUND", "error_message": "Eval case not found"})
                continue
            merged = dict(existing)
            if "enabled" in updates:
                merged["enabled"] = updates["enabled"]
            if "severity" in updates:
                merged["severity"] = updates["severity"]
            if "category" in updates:
                merged["category"] = updates["category"]
            if tags_add or tags_remove:
                current_tags = list(merged.get("tags") or [])
                for tag in tags_add:
                    if tag not in current_tags:
                        current_tags.append(tag)
                current_tags = [t for t in current_tags if t not in tags_remove]
                merged["tags"] = current_tags
            if notes_append:
                existing_notes = (merged.get("notes") or "").strip()
                merged["notes"] = f"{existing_notes}\n{notes_append}".strip() if existing_notes else notes_append
            merged["updated_at"] = utc_now_iso()
            case = EvalCase.from_dict(merged)
            self.case_repository.save_case(case.to_dict())
            items.append({"case_id": case_id, "status": "updated"})
            updated_count += 1
        return {"updated_count": updated_count, "failed_count": len(case_ids) - updated_count, "items": items}

    def clone_case(self, case_id: str, payload: dict | None = None) -> dict | None:
        existing = self.get_case(case_id)
        if existing is None:
            return None
        new_id = new_eval_case_id(existing.get("agent_name", "unknown"))
        payload = payload or {}
        metadata = dict(existing.get("metadata") or {})
        metadata["cloned_from_case_id"] = case_id
        # Node Eval 字段：保留 eval_scope / node_name / source_* / prompt_* / model
        # 老 case 没有 eval_scope 时默认为 agent，clone 后保持原状（不强制改 node）。
        cloned = {
            "case_id": new_id,
            "agent_name": existing.get("agent_name", "unknown"),
            "title": payload.get("title") or f"Copy of {existing.get('title') or case_id}",
            "description": existing.get("description"),
            "tags": list(existing.get("tags") or []),
            "source": "manual",
            "input": existing.get("input"),
            "mock_context": existing.get("mock_context"),
            "mock_tool_outputs": existing.get("mock_tool_outputs"),
            "expected_behavior": existing.get("expected_behavior"),
            "expected_output_fields": list(existing.get("expected_output_fields") or []),
            "expected_tools": list(existing.get("expected_tools") or []),
            "expected_data_limitations": list(existing.get("expected_data_limitations") or []),
            "forbidden_behavior": list(existing.get("forbidden_behavior") or []),
            "scoring_rubric": existing.get("scoring_rubric"),
            "notes": existing.get("notes"),
            "metadata": metadata,
            "enabled": payload.get("enabled") if "enabled" in payload else False,
            "severity": existing.get("severity"),
            "category": existing.get("category"),
            "version": 1,
            "eval_scope": existing.get("eval_scope", "agent"),
            "node_name": existing.get("node_name"),
            "source_run_id": existing.get("source_run_id"),
            "source_llm_call_id": existing.get("source_llm_call_id"),
            "source_node_trace_id": existing.get("source_node_trace_id"),
            "prompt_key": existing.get("prompt_key"),
            "prompt_version": existing.get("prompt_version"),
            "prompt_hash": existing.get("prompt_hash"),
            "model": existing.get("model"),
            "archived": False,
            "archived_at": None,
            "archived_reason": None,
        }
        case = EvalCase.from_dict(cloned)
        return self.case_repository.save_case(case.to_dict())

    def seed_builtin_cases(self, *, force: bool = False) -> dict:
        return self.case_repository.seed_builtin_cases(force=force)

    def build_case_from_replay(self, replay_id: str, *, save: bool = False) -> dict | None:
        if self.replay_service is None:
            return None
        snapshot = self.replay_service.get_snapshot(replay_id)
        if snapshot is None:
            return None
        case = build_eval_case_from_replay(snapshot)
        if save:
            return self.case_repository.save_case(case.to_dict())
        return case.to_dict()

    def build_case_from_llm_call(self, call_id: str, *, save: bool = False) -> dict | None:
        if self.llm_call_service is None:
            raise ValueError("LLM call service not configured")
        call = self.llm_call_service.get_call(call_id)
        if call is None:
            return None
        case = build_node_eval_case_from_llm_call(call)
        if save:
            return self.case_repository.save_case(case.to_dict())
        return case.to_dict()

    def build_case_from_node_trace(
        self,
        run_id: str,
        node_trace_id: str,
        *,
        save: bool = False,
    ) -> dict | None:
        if self.run_trace_repository is None:
            raise ValueError("Run trace repository not configured")
        run = self.run_trace_repository.get_trace(run_id)
        if run is None:
            return None
        node_trace, index = find_node_trace_by_id(run, node_trace_id)
        if node_trace is None:
            return None
        case = build_node_eval_case_from_node_trace(run, node_trace, node_trace_id=node_trace_id, index=index)
        if save:
            return self.case_repository.save_case(case.to_dict())
        return case.to_dict()

    def select_cases_for_eval(
        self,
        *,
        agent_name: str | None = None,
        case_ids: list[str] | None = None,
        tag: str | None = None,
        severity: str | None = None,
        category: str | None = None,
        eval_scope: str | None = None,
        node_name: str | None = None,
        enabled_only: bool = True,
        include_judge: bool = True,
        limit: int = 100,
    ) -> list[dict]:
        if case_ids:
            cases = []
            for cid in case_ids:
                case = self.get_case(cid)
                if case:
                    cases.append(case)
            if eval_scope:
                cases = [c for c in cases if c.get("eval_scope", "agent") == eval_scope]
            if node_name:
                cases = [c for c in cases if c.get("node_name") == node_name]
            return cases

        kwargs: dict = {"limit": limit}
        if agent_name:
            kwargs["agent_name"] = agent_name
        if tag:
            kwargs["tag"] = tag
        if severity:
            kwargs["severity"] = severity
        if category:
            kwargs["category"] = category
        if eval_scope:
            kwargs["eval_scope"] = eval_scope
        if node_name:
            kwargs["node_name"] = node_name
        if enabled_only:
            kwargs["enabled"] = True
        cases = self.list_cases(**kwargs)
        if enabled_only:
            cases = [c for c in cases if _case_is_enabled(c)]
        cases = [c for c in cases if not _case_is_archived(c)]

        if not include_judge:
            cases = [c for c in cases if c.get("judge_enabled") is not True]
        return cases

    def run_eval(
        self,
        *,
        case_ids: list[str] | None = None,
        agent_name: str | None = None,
        replay_ids: list[str] | None = None,
        mode: str = "static",
        name: str | None = None,
    ) -> dict:
        eval_run = EvalRun(
            eval_run_id=new_eval_run_id(),
            name=name or f"{mode} eval run",
            agent_name=agent_name,
            case_ids=list(case_ids or []),
            config={"mode": mode, "trigger": "case_ids" if case_ids else "agent_name", "requested_case_count": len(case_ids or [])},
        )
        if mode == "live_mock":
            eval_run.config["live_mock_strategy"] = "prompt_adapter"
        results: list[dict] = []

        if mode == "live_mock":
            if replay_ids:
                results.append(
                    EvalCaseResult(
                        case_id="live_mock_requires_case_ids",
                        agent_name=agent_name or "unknown",
                        status="warning",
                        score=0,
                        max_score=0,
                        checks=[],
                        error_code="LIVE_MOCK_REQUIRES_CASE_IDS",
                        error_message="Live mock eval requires case_ids, not replay_ids",
                    ).to_dict()
                )
            for case_id in case_ids or []:
                result = self._evaluate_case_live_mock(case_id)
                if result:
                    results.append(result)
            if not results and not replay_ids and agent_name:
                for case in self.list_cases(agent_name=agent_name, enabled=True, limit=100):
                    cid = case.get("case_id")
                    if cid:
                        result = self._evaluate_case_live_mock(cid)
                        if result:
                            results.append(result)
        elif mode == "static":
            for replay_id in replay_ids or []:
                result = self._evaluate_replay(replay_id)
                if result:
                    results.append(result)
            for case_id in case_ids or []:
                result = self._evaluate_case_id(case_id)
                if result:
                    results.append(result)
            if not results and agent_name:
                for case in self.list_cases(agent_name=agent_name, enabled=True, limit=100):
                    results.append(self._evaluate_case(case, output=(case.get("metadata") or {}).get("output") or {}))
        else:
            results.append(
                EvalCaseResult(
                    case_id=f"mode_{mode}_not_implemented",
                    agent_name=agent_name or "unknown",
                    status="warning",
                    score=0,
                    max_score=0,
                    checks=[],
                    error_code="MODE_NOT_IMPLEMENTED",
                    error_message=f"Eval mode '{mode}' is not implemented. Supported modes: static, live_mock",
                ).to_dict()
            )

        eval_run.finished_at = utc_now_iso()
        eval_run.status = "completed"
        eval_run.results = results
        eval_run.case_ids = [result.get("case_id") for result in results if result.get("case_id")]
        eval_run.summary = self._summary(results)
        judge_case_count = sum(1 for r in results if (r.get("metadata") or {}).get("judge_enabled"))
        if judge_case_count > 0:
            eval_run.config["judge_enabled"] = True
            eval_run.config["judge_case_count"] = judge_case_count
        return self.run_repository.save_run(eval_run.to_dict())

    def get_eval_run(self, eval_run_id: str) -> dict | None:
        return self.run_repository.get_run(eval_run_id)

    def list_eval_runs(self, *, hours: int = 24, agent_name: str | None = None, limit: int = 100) -> dict:
        items = self.run_repository.list_runs(hours=hours, agent_name=agent_name, limit=limit)
        return {"items": items, "summary": {"run_count": len(items)}}

    def get_correctness_summary(
        self,
        *,
        agent_name: str | None = None,
        hours: int = 24 * 30,
        limit: int = 1000,
    ) -> dict:
        """Eval P3 Stage 06: 跨 Agent 正确性报告。

        没有 judge 数据时返回空结构，不报错。
        """
        runs = self.run_repository.list_runs(hours=hours, agent_name=agent_name, limit=limit)
        judged_case_count = 0
        sum_overall_score = 0.0
        failed_dimension_counts: dict[str, int] = {}
        warning_dimension_counts: dict[str, int] = {}
        by_agent: dict[str, dict[str, Any]] = {}
        by_dimension: dict[str, dict[str, Any]] = {}
        recent_failures: list[dict[str, Any]] = []

        high_risk_failure_count = 0

        for run in runs or []:
            run_id = run.get("eval_run_id", "")
            results = run.get("results") or []
            for r in results:
                meta = r.get("metadata") or {}
                judge = meta.get("judge")
                if not isinstance(judge, dict):
                    continue
                judged_case_count += 1
                overall = float(judge.get("overall_score", 0.0) or 0.0)
                sum_overall_score += overall
                failed_dims = list(judge.get("failed_dimensions") or [])
                warnings = list(judge.get("warnings") or [])
                failure_reasons = list(judge.get("failure_reasons") or [])
                agent = str(meta.get("eval_scope") and r.get("agent_name", "") or r.get("agent_name", ""))
                if not agent:
                    agent = "unknown"
                if not judge.get("passed", False):
                    high_risk_failure_count += 1
                    recent_failures.append(
                        {
                            "eval_run_id": run_id,
                            "case_id": r.get("case_id", ""),
                            "agent_name": agent,
                            "failed_dimensions": failed_dims,
                            "failure_reasons": failure_reasons,
                        }
                    )

                # 维度聚合
                for dim in failed_dims:
                    failed_dimension_counts[dim] = failed_dimension_counts.get(dim, 0) + 1
                    by_dimension.setdefault(dim, {"dimension": dim, "failed_count": 0, "warning_count": 0, "score_sum": 0.0, "score_count": 0, "affected_agents": set()})
                    by_dimension[dim]["failed_count"] += 1
                    by_dimension[dim]["affected_agents"].add(agent)
                for dim in warnings:
                    warning_dimension_counts[dim] = warning_dimension_counts.get(dim, 0) + 1
                    by_dimension.setdefault(dim, {"dimension": dim, "failed_count": 0, "warning_count": 0, "score_sum": 0.0, "score_count": 0, "affected_agents": set()})
                    by_dimension[dim]["warning_count"] += 1
                dim_scores = judge.get("dimension_scores") or {}
                if isinstance(dim_scores, dict):
                    for dim, score in dim_scores.items():
                        by_dimension.setdefault(dim, {"dimension": dim, "failed_count": 0, "warning_count": 0, "score_sum": 0.0, "score_count": 0, "affected_agents": set()})
                        try:
                            by_dimension[dim]["score_sum"] += float(score)
                            by_dimension[dim]["score_count"] += 1
                        except (TypeError, ValueError):
                            pass

                # Agent 聚合
                bucket = by_agent.setdefault(agent, {
                    "agent_name": agent,
                    "judged_case_count": 0,
                    "score_sum": 0.0,
                    "failed_count": 0,
                    "weakest_dim_scores": {},
                })
                bucket["judged_case_count"] += 1
                bucket["score_sum"] += overall
                if not judge.get("passed", False):
                    bucket["failed_count"] += 1
                for dim, score in dim_scores.items():
                    try:
                        f_score = float(score)
                    except (TypeError, ValueError):
                        continue
                    cur = bucket["weakest_dim_scores"].get(dim)
                    if cur is None or f_score < cur:
                        bucket["weakest_dim_scores"][dim] = f_score

        # 收尾
        avg_overall_score = sum_overall_score / judged_case_count if judged_case_count else 0.0
        by_agent_out = []
        for agent, info in by_agent.items():
            count = info["judged_case_count"]
            avg_score = info["score_sum"] / count if count else 0.0
            # weakest_dimensions：取分数最低的 1-3 个
            sorted_dims = sorted(info["weakest_dim_scores"].items(), key=lambda x: x[1])
            weakest = [d for d, _ in sorted_dims[:3]]
            by_agent_out.append(
                {
                    "agent_name": agent,
                    "judged_case_count": count,
                    "avg_overall_score": round(avg_score, 3),
                    "weakest_dimensions": weakest,
                    "failed_count": info["failed_count"],
                }
            )
        by_agent_out.sort(key=lambda x: (-x["failed_count"], x["agent_name"]))

        by_dimension_out = []
        for dim, info in by_dimension.items():
            count = info["score_count"]
            avg_score = info["score_sum"] / count if count else 0.0
            affected = sorted(info["affected_agents"])
            by_dimension_out.append(
                {
                    "dimension": dim,
                    "avg_score": round(avg_score, 3),
                    "failed_count": info["failed_count"],
                    "warning_count": info["warning_count"],
                    "affected_agents": affected,
                }
            )
        by_dimension_out.sort(key=lambda x: -x["failed_count"])

        recent_failures = recent_failures[:20]

        return {
            "summary": {
                "eval_run_count": len(runs or []),
                "judged_case_count": judged_case_count,
                "avg_overall_score": round(avg_overall_score, 3),
                "failed_dimension_count": sum(failed_dimension_counts.values()),
                "high_risk_failure_count": high_risk_failure_count,
            },
            "by_agent": by_agent_out,
            "by_dimension": by_dimension_out,
            "recent_failures": recent_failures,
        }

    def compare_eval_runs(self, baseline_run_id: str, candidate_run_id: str) -> dict | None:
        baseline = self.get_eval_run(baseline_run_id)
        candidate = self.get_eval_run(candidate_run_id)
        if baseline is None or candidate is None:
            return None

        baseline_results = baseline.get("results") or []
        candidate_results = candidate.get("results") or []

        baseline_by_case = {r["case_id"]: r for r in baseline_results if r.get("case_id")}
        candidate_by_case = {r["case_id"]: r for r in candidate_results if r.get("case_id")}

        all_case_ids = set(baseline_by_case.keys()) | set(candidate_by_case.keys())

        status_changes = []
        new_failures = []
        fixed_cases = []
        still_failing = []
        check_regressions = []
        missing_in_candidate = []
        new_cases_in_candidate = []

        for case_id in sorted(all_case_ids):
            b_result = baseline_by_case.get(case_id)
            c_result = candidate_by_case.get(case_id)

            if b_result and c_result:
                diff = _build_case_diff(b_result, c_result)
                status_changes.append(diff)
                b_rank = _result_status_rank(b_result.get("status"))
                c_rank = _result_status_rank(c_result.get("status"))
                if b_rank == 0 and c_rank > 0:
                    new_failures.append(diff)
                elif b_rank > 0 and c_rank == 0:
                    fixed_cases.append(diff)
                elif b_rank > 0 and c_rank > 0:
                    still_failing.append(diff)
                if diff.get("new_failed_checks"):
                    check_regressions.append(diff)
            elif b_result and not c_result:
                diff = {
                    "case_id": case_id,
                    "agent_name": b_result.get("agent_name", ""),
                    "baseline_status": b_result.get("status", ""),
                    "candidate_status": "missing",
                    "baseline_score": b_result.get("score", 0),
                    "candidate_score": 0,
                    "baseline_max_score": b_result.get("max_score", 0),
                    "candidate_max_score": 0,
                    "score_delta": -(b_result.get("score") or 0),
                    "severity": _result_severity(b_result),
                    "category": _result_category(b_result),
                    "baseline_failed_checks": sorted(c for c in _result_failed_checks(b_result)),
                    "candidate_failed_checks": [],
                    "new_failed_checks": [],
                    "fixed_failed_checks": [],
                    "message": "Case missing in candidate run",
                }
                missing_in_candidate.append(diff)
                status_changes.append(diff)
            elif c_result and not b_result:
                diff = {
                    "case_id": case_id,
                    "agent_name": c_result.get("agent_name", ""),
                    "baseline_status": "missing",
                    "candidate_status": c_result.get("status", ""),
                    "baseline_score": 0,
                    "candidate_score": c_result.get("score", 0),
                    "baseline_max_score": 0,
                    "candidate_max_score": c_result.get("max_score", 0),
                    "score_delta": c_result.get("score") or 0,
                    "severity": _result_severity(c_result),
                    "category": _result_category(c_result),
                    "baseline_failed_checks": [],
                    "candidate_failed_checks": sorted(c for c in _result_failed_checks(c_result)),
                    "new_failed_checks": sorted(c for c in _result_failed_checks(c_result)),
                    "fixed_failed_checks": [],
                    "message": "New case in candidate run",
                }
                new_cases_in_candidate.append(diff)
                status_changes.append(diff)
                if _result_status_rank(c_result.get("status")) > 0:
                    new_failures.append(diff)

        baseline_summary = baseline.get("summary") or {}
        candidate_summary = candidate.get("summary") or {}

        critical_regression_count = sum(
            1 for d in new_failures + still_failing
            if d.get("severity") == "critical"
        )
        high_priority_regression_count = sum(
            1 for d in new_failures + still_failing
            if d.get("severity") in {"high", "critical"}
        )

        return {
            "baseline_run_id": baseline_run_id,
            "candidate_run_id": candidate_run_id,
            "baseline_name": baseline.get("name", ""),
            "candidate_name": candidate.get("name", ""),
            "summary": {
                "baseline_case_count": len(baseline_results),
                "candidate_case_count": len(candidate_results),
                "common_case_count": len(set(baseline_by_case.keys()) & set(candidate_by_case.keys())),
                "baseline_pass_rate": baseline_summary.get("pass_rate", 0),
                "candidate_pass_rate": candidate_summary.get("pass_rate", 0),
                "pass_rate_delta": (candidate_summary.get("pass_rate", 0) or 0) - (baseline_summary.get("pass_rate", 0) or 0),
                "baseline_score_rate": baseline_summary.get("score_rate", 0),
                "candidate_score_rate": candidate_summary.get("score_rate", 0),
                "score_rate_delta": (candidate_summary.get("score_rate", 0) or 0) - (baseline_summary.get("score_rate", 0) or 0),
                "new_failure_count": len(new_failures),
                "fixed_case_count": len(fixed_cases),
                "still_failing_count": len(still_failing),
                "missing_in_candidate_count": len(missing_in_candidate),
                "new_case_in_candidate_count": len(new_cases_in_candidate),
                "critical_regression_count": critical_regression_count,
                "high_priority_regression_count": high_priority_regression_count,
            },
            "new_failures": new_failures,
            "fixed_cases": fixed_cases,
            "still_failing": still_failing,
            "missing_in_candidate": missing_in_candidate,
            "new_cases_in_candidate": new_cases_in_candidate,
            "status_changes": status_changes,
            "check_regressions": check_regressions,
            "severity_delta": _build_delta(baseline_results, candidate_results, "severity"),
            "category_delta": _build_delta(baseline_results, candidate_results, "category"),
            "check_delta": _build_check_delta(baseline_results, candidate_results),
        }

    def run_agent_regression_eval(self, payload: dict) -> dict:
        agent_name = payload["agent_name"]
        mode = payload.get("mode", "static")
        if mode not in {"static", "live_mock"}:
            raise ValueError(f"Invalid mode: {mode}")

        case_tag = payload.get("case_tag")
        severity = payload.get("severity")
        category = payload.get("category")
        include_disabled = payload.get("include_disabled", False)
        include_judge = payload.get("include_judge", False)
        limit = payload.get("limit", 100)
        trigger = payload.get("trigger", "manual")
        prompt_meta = payload.get("prompt") or {}
        model_meta = payload.get("model") or {}
        git_meta = payload.get("git") or {}
        baseline_eval_run_id = payload.get("baseline_eval_run_id")
        name = payload.get("name")
        include_node_eval = bool(payload.get("include_node_eval", False))
        node_name = payload.get("node_name") or None

        gate_config = dict(_DEFAULT_GATE)
        gate_config.update({k: v for k, v in (payload.get("gate") or {}).items() if v is not None})

        shared_selector_kwargs = dict(
            agent_name=agent_name,
            tag=case_tag,
            severity=severity,
            category=category,
            enabled_only=not include_disabled,
        )

        # Agent Eval Cases（始终选择 eval_scope=agent）
        agent_kwargs = dict(shared_selector_kwargs, eval_scope="agent", limit=limit)
        all_matched_agent_cases = self.select_cases_for_eval(**agent_kwargs, include_judge=True)
        selected_agent_cases = self.select_cases_for_eval(**agent_kwargs, include_judge=include_judge)
        agent_skipped_judge = len(all_matched_agent_cases) - len(selected_agent_cases)

        # Node Eval Cases（仅当 include_node_eval=True 时选择）
        selected_node_cases: list[dict] = []
        node_skipped_judge = 0
        if include_node_eval:
            node_kwargs = dict(shared_selector_kwargs, eval_scope="node", limit=limit)
            if node_name:
                node_kwargs["node_name"] = node_name
            all_matched_node_cases = self.select_cases_for_eval(**node_kwargs, include_judge=True)
            selected_node_cases = self.select_cases_for_eval(**node_kwargs, include_judge=include_judge)
            node_skipped_judge = len(all_matched_node_cases) - len(selected_node_cases)

        # 去重合并
        seen_ids: set[str] = set()
        merged_cases: list[dict] = []
        for c in selected_agent_cases + selected_node_cases:
            cid = c.get("case_id")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                merged_cases.append(c)

        skipped_judge_case_count = agent_skipped_judge + node_skipped_judge

        if not merged_cases:
            raise ValueError("No eval cases matched regression selector")

        case_ids = [c["case_id"] for c in merged_cases]

        now = utc_now_iso()
        if not name:
            name_parts = ["Agent Regression", agent_name, mode]
            if include_node_eval:
                name_parts.append("node_eval")
            if node_name:
                name_parts.append(f"node={node_name}")
            if prompt_meta.get("prompt_version"):
                name_parts.append(f"prompt {prompt_meta['prompt_version']}")
            else:
                name_parts.append(now[:16].replace("T", " "))
            name = " - ".join(name_parts)

        eval_result = self.run_eval(
            case_ids=case_ids,
            agent_name=agent_name,
            mode=mode,
            name=name,
        )

        summary = eval_result.get("summary", {})
        gate_result = _evaluate_gate_dict(summary, gate_config)

        scope_breakdown = _build_scope_breakdown(eval_result.get("results") or [])
        agent_pass_rate = scope_breakdown.get("agent", {}).get("pass_rate")
        node_pass_rate = scope_breakdown.get("node", {}).get("pass_rate") if include_node_eval else None
        node_failed_count = scope_breakdown.get("node", {}).get("failed_count", 0) if include_node_eval else 0
        agent_failed_count = scope_breakdown.get("agent", {}).get("failed_count", 0)

        if include_node_eval and node_failed_count > 0:
            existing_reasons = list(gate_result.get("reasons") or [])
            extra = [f"node_failed_count {node_failed_count} > 0"]
            if node_pass_rate is not None:
                extra.append(f"node_pass_rate {node_pass_rate:.3f} indicates node eval regression")
            gate_result = {
                **gate_result,
                "node_failed_count": node_failed_count,
                "node_case_count": scope_breakdown.get("node", {}).get("case_count", 0),
                "node_pass_rate": node_pass_rate,
                "agent_failed_count": agent_failed_count,
                "agent_case_count": scope_breakdown.get("agent", {}).get("case_count", 0),
                "agent_pass_rate": agent_pass_rate,
                "reasons": existing_reasons + extra,
            }
        else:
            gate_result = {
                **gate_result,
                "node_failed_count": node_failed_count,
                "node_case_count": scope_breakdown.get("node", {}).get("case_count", 0) if include_node_eval else 0,
                "node_pass_rate": node_pass_rate,
                "agent_failed_count": agent_failed_count,
                "agent_case_count": scope_breakdown.get("agent", {}).get("case_count", 0),
                "agent_pass_rate": agent_pass_rate,
            }

        config_patch: dict = {
            "run_type": "agent_regression",
            "trigger": trigger,
            "agent_name": agent_name,
            "mode": mode,
            "case_selector": {
                "case_tag": case_tag,
                "severity": severity,
                "category": category,
                "include_disabled": include_disabled,
                "include_judge": include_judge,
                "limit": limit,
                "include_node_eval": include_node_eval,
                "node_name": node_name,
            },
            "gate": gate_config,
            "gate_result": gate_result,
            "prompt": prompt_meta,
            "model": model_meta,
            "git": git_meta,
            "baseline_eval_run_id": baseline_eval_run_id,
            "selected_case_count": len(merged_cases),
            "selected_agent_case_count": len(selected_agent_cases),
            "selected_node_case_count": len(selected_node_cases),
            "skipped_judge_case_count": skipped_judge_case_count,
            "scope_breakdown": scope_breakdown,
        }

        eval_run = dict(eval_result)
        eval_run_config = dict(eval_run.get("config") or {})
        eval_run_config.update(config_patch)
        eval_run["config"] = eval_run_config
        eval_run = self.run_repository.save_run(eval_run)

        baseline_compare_result = None
        if baseline_eval_run_id:
            baseline = self.get_eval_run(baseline_eval_run_id)
            if baseline is None:
                eval_run["config"]["baseline_compare_error"] = "Baseline eval run not found"
                eval_run = self.run_repository.save_run(eval_run)
            else:
                baseline_compare_result = self.compare_eval_runs(baseline_eval_run_id, eval_run["eval_run_id"])
                if baseline_compare_result:
                    eval_run["config"]["baseline_compared"] = True
                    eval_run["config"]["baseline_compare_summary"] = baseline_compare_result.get("summary", {})
                    eval_run = self.run_repository.save_run(eval_run)

        return {
            "eval_run": eval_run,
            "gate_result": gate_result,
            "baseline_compare_result": baseline_compare_result,
            "selected_case_count": len(merged_cases),
            "selected_agent_case_count": len(selected_agent_cases),
            "selected_node_case_count": len(selected_node_cases),
            "skipped_judge_case_count": skipped_judge_case_count,
            "scope_breakdown": scope_breakdown,
            "skipped_disabled_case_count": 0,
        }

    def _evaluate_replay(self, replay_id: str) -> dict | None:
        if self.replay_service is None:
            return None
        snapshot = self.replay_service.get_snapshot(replay_id)
        if snapshot is None:
            return EvalCaseResult(
                case_id=f"replay_missing_{replay_id}",
                agent_name="unknown",
                status="error",
                score=0,
                max_score=0,
                checks=[],
                error_code="REPLAY_NOT_FOUND",
                error_message="Replay snapshot not found",
                replay_id=replay_id,
            ).to_dict()
        case = build_eval_case_from_replay(snapshot)
        return self._evaluate_case(case.to_dict(), output=snapshot.get("final_output") or {}, replay=snapshot)

    def _evaluate_case_id(self, case_id: str) -> dict | None:
        case = self.get_case(case_id)
        if case is None:
            return EvalCaseResult(
                case_id=case_id,
                agent_name="unknown",
                status="error",
                score=0,
                max_score=0,
                checks=[],
                error_code="CASE_NOT_FOUND",
                error_message="Eval case not found",
            ).to_dict()
        output = (case.get("metadata") or {}).get("output")
        if output is None:
            return EvalCaseResult(
                case_id=case_id,
                agent_name=case.get("agent_name", "unknown"),
                status="warning",
                score=0,
                max_score=0,
                checks=[],
                error_code="NO_OUTPUT_TO_EVALUATE",
                error_message="Static mode requires replay_ids or metadata.output",
            ).to_dict()
        return self._evaluate_case(case, output=output)

    def _evaluate_case(self, case: dict, *, output: dict, replay: dict | None = None, eval_mode: str = "static") -> dict:
        checks = run_eval_checks(output, case, replay=replay)

        judge_result = None
        if case.get("judge_enabled"):
            judge_result = self.judge_service.judge(case=case, output=output, eval_mode=eval_mode)
            judge_details: dict = judge_result.get("raw") or {}
            if judge_result.get("error_code"):
                judge_details["error_code"] = judge_result["error_code"]
                judge_details["error_message"] = judge_result.get("error_message")
            judge_check = CheckResult(
                check_name="llm_judge",
                passed=judge_result.get("passed", False),
                severity="warning" if not judge_result.get("passed") else "info",
                score=judge_result.get("score", 0),
                max_score=judge_result.get("max_score", 100),
                message=f"LLM judge {judge_result.get('verdict', 'unknown')}: score {judge_result.get('score', 0)}/{judge_result.get('max_score', 100)}",
                details=judge_details,
            )
            checks.append(judge_check)

        # Eval P3 Stage 06: 跨 Agent correctness judge
        # 仅在 case 显式打开 correctness_judge_enabled 时调用，避免影响已有 judge 行为
        correctness_judge_result = None
        if case.get("correctness_judge_enabled"):
            eval_scope = case.get("eval_scope", "agent")
            node_name = case.get("node_name")
            correctness_judge_result = self.judge_service.judge_correctness(
                case=case,
                output=output,
                eval_scope=eval_scope,
                node_name=node_name,
                eval_mode=eval_mode,
            )
            raw = correctness_judge_result.get("raw") or {}
            failed_dims = raw.get("failed_dimensions") or []
            severity = "high" if failed_dims else ("warning" if not correctness_judge_result.get("passed") else "info")
            judge_check = CheckResult(
                check_name="llm_judge_correctness",
                passed=correctness_judge_result.get("passed", False),
                severity=severity,
                score=correctness_judge_result.get("score", 0),
                max_score=1.0,
                message=(
                    f"LLM correctness judge: overall_score {correctness_judge_result.get('score', 0):.2f}, "
                    f"failed_dimensions={failed_dims}"
                ),
                details=raw,
            )
            checks.append(judge_check)

        score = sum(check.score for check in checks)
        max_score = sum(check.max_score for check in checks)
        fatal_failed = any(not check.passed and check.severity == "fatal" for check in checks)
        high_critical_failed = any(
            not check.passed and check.severity in {"fatal", "critical", "high"}
            for check in checks
        )
        warning_failed = any(not check.passed for check in checks)
        status = "failed" if (fatal_failed or high_critical_failed) else "warning" if warning_failed else "passed"

        metadata: dict = {
            "source": case.get("source"),
            "severity": case.get("severity", "medium"),
            "category": case.get("category", ""),
            "tags": case.get("tags", []),
            "eval_mode": eval_mode,
            "eval_scope": case.get("eval_scope", "agent"),
            "node_name": case.get("node_name"),
            "prompt_key": case.get("prompt_key"),
            "prompt_version": case.get("prompt_version"),
            "model": case.get("model"),
        }
        if judge_result is not None:
            metadata["judge_enabled"] = True
            metadata["judge_verdict"] = judge_result.get("verdict")
            metadata["judge_score"] = judge_result.get("score")
        elif case.get("judge_enabled"):
            metadata["judge_enabled"] = True

        if correctness_judge_result is not None:
            raw = correctness_judge_result.get("raw") or {}
            metadata["judge"] = {
                "passed": correctness_judge_result.get("passed", False),
                "overall_score": correctness_judge_result.get("score", 0.0),
                "dimension_scores": raw.get("dimension_scores", {}),
                "failed_dimensions": raw.get("failed_dimensions", []),
                "warnings": raw.get("warnings", []),
                "failure_reasons": raw.get("failure_reasons", []),
                "confidence": raw.get("confidence", 0.0),
            }
            metadata["correctness_judge_enabled"] = True
            if correctness_judge_result.get("error_code"):
                metadata["judge_error_code"] = correctness_judge_result["error_code"]
        elif case.get("correctness_judge_enabled"):
            metadata["correctness_judge_enabled"] = True

        return EvalCaseResult(
            case_id=case["case_id"],
            agent_name=case.get("agent_name", "unknown"),
            status=status,
            score=score,
            max_score=max_score,
            checks=[check.to_dict() for check in checks],
            output_summary={"fields": sorted(output.keys()) if isinstance(output, dict) else [], "type": type(output).__name__},
            replay_id=(replay or {}).get("replay_id"),
            run_id=(replay or {}).get("run_id"),
            metadata=metadata,
        ).to_dict()

    def _evaluate_case_live_mock(self, case_id: str) -> dict | None:
        case = self.get_case(case_id)
        if case is None:
            return EvalCaseResult(
                case_id=case_id,
                agent_name="unknown",
                status="error",
                score=0,
                max_score=0,
                checks=[],
                error_code="CASE_NOT_FOUND",
                error_message="Eval case not found",
                metadata={"eval_mode": "live_mock"},
            ).to_dict()

        mock_result = self.live_mock_executor.run_case(case)
        if mock_result.get("error_code"):
            return EvalCaseResult(
                case_id=case_id,
                agent_name=case.get("agent_name", "unknown"),
                status="error" if mock_result["error_code"] != "LIVE_MOCK_AGENT_NOT_SUPPORTED" else "warning",
                score=0,
                max_score=0,
                checks=[],
                error_code=mock_result["error_code"],
                error_message=mock_result.get("error_message", ""),
                metadata=mock_result.get("metadata", {"eval_mode": "live_mock"}),
            ).to_dict()

        output = mock_result.get("output") or {}
        replay_like = {
            "tool_snapshots": (case.get("mock_tool_outputs") or {}).get("tool_snapshots", []),
            "data_limitations": case.get("expected_data_limitations") or [],
        }
        result = self._evaluate_case(case, output=output, replay=replay_like, eval_mode="live_mock")
        result_metadata = dict(result.get("metadata") or {})
        result_metadata.update(mock_result.get("metadata") or {})
        result["metadata"] = result_metadata
        return result

    # ── Bad Case Feedback ─────────────────────────────────────────────

    def create_feedback(self, payload: dict) -> dict:
        if not payload.get("source_type"):
            raise ValueError("source_type is required")
        if not payload.get("source_id"):
            raise ValueError("source_id is required")
        if not payload.get("title"):
            raise ValueError("title is required")
        severity = payload.get("severity", "medium")
        if severity not in _SEVERITY_VALUES:
            raise ValueError(f"Invalid severity: {severity}")
        issue_type = payload.get("issue_type", "other")
        if issue_type not in VALID_FEEDBACK_ISSUE_TYPES:
            raise ValueError(f"Invalid issue_type: {issue_type}")
        category = payload.get("category", "")
        if category and category not in VALID_FEEDBACK_CATEGORIES:
            raise ValueError(f"Invalid category: {category}")

        feedback = BadCaseFeedback(
            feedback_id=new_feedback_id(),
            source_type=payload["source_type"],
            source_id=payload["source_id"],
            title=payload["title"],
            agent_name=payload.get("agent_name", ""),
            description=payload.get("description", ""),
            issue_type=issue_type,
            severity=severity,
            category=category,
            tags=list(payload.get("tags") or []),
            status="open",
            notes=payload.get("notes", ""),
            replay_id=payload.get("replay_id"),
            run_id=payload.get("run_id"),
            eval_run_id=payload.get("eval_run_id"),
            case_id=payload.get("case_id"),
            result_case_id=payload.get("result_case_id"),
            evidence=dict(payload.get("evidence") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )
        if self.feedback_repository is None:
            raise ValueError("Feedback repository not configured")
        return self.feedback_repository.save_feedback(feedback.to_dict())

    def get_feedback(self, feedback_id: str) -> dict | None:
        if self.feedback_repository is None:
            return None
        return self.feedback_repository.get_feedback(feedback_id)

    def list_feedback(
        self,
        *,
        status: str | None = None,
        source_type: str | None = None,
        agent_name: str | None = None,
        severity: str | None = None,
        category: str | None = None,
        issue_type: str | None = None,
        tag: str | None = None,
        eval_run_id: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> dict:
        if self.feedback_repository is None:
            return {"items": [], "summary": {"count": 0, "by_status": {}, "by_severity": {}, "by_issue_type": {}}}
        items = self.feedback_repository.list_feedback(
            status=status, source_type=source_type, agent_name=agent_name,
            severity=severity, category=category, issue_type=issue_type,
            tag=tag, eval_run_id=eval_run_id, query=query, limit=limit,
        )
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_issue_type: dict[str, int] = {}
        for item in items:
            s = item.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
            sev = item.get("severity", "medium")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            it = item.get("issue_type", "other")
            by_issue_type[it] = by_issue_type.get(it, 0) + 1
        return {
            "items": items,
            "summary": {
                "count": len(items),
                "by_status": by_status,
                "by_severity": by_severity,
                "by_issue_type": by_issue_type,
            },
        }

    def update_feedback(self, feedback_id: str, updates: dict) -> dict | None:
        if self.feedback_repository is None:
            return None
        existing = self.feedback_repository.get_feedback(feedback_id)
        if existing is None:
            return None
        allowed = {"title", "description", "issue_type", "severity", "category", "tags", "status", "notes", "metadata"}
        merged = dict(existing)
        for key, value in updates.items():
            if key in allowed:
                merged[key] = value
        new_status = merged.get("status", "open")
        if new_status not in VALID_FEEDBACK_STATUSES:
            raise ValueError(f"Invalid status: {new_status}")
        new_severity = merged.get("severity", "medium")
        if new_severity not in _SEVERITY_VALUES:
            raise ValueError(f"Invalid severity: {new_severity}")
        new_issue_type = merged.get("issue_type", "other")
        if new_issue_type not in VALID_FEEDBACK_ISSUE_TYPES:
            raise ValueError(f"Invalid issue_type: {new_issue_type}")
        merged["updated_at"] = utc_now_iso()
        return self.feedback_repository.save_feedback(merged)

    def create_eval_case_from_feedback(self, feedback_id: str, payload: dict | None = None) -> dict | None:
        if self.feedback_repository is None:
            return None
        feedback = self.feedback_repository.get_feedback(feedback_id)
        if feedback is None:
            return None

        source_type = feedback.get("source_type", "")
        case_dict: dict | None = None

        if source_type == "replay" and feedback.get("replay_id"):
            snapshot = None
            if self.replay_service:
                snapshot = self.replay_service.get_snapshot(feedback["replay_id"])
            if snapshot:
                case = build_eval_case_from_replay(snapshot)
                case_dict = case.to_dict()

        elif source_type == "eval_result":
            result_case_id = feedback.get("result_case_id") or feedback.get("case_id")
            if result_case_id:
                existing_case = self.get_case(result_case_id)
                if existing_case:
                    case_dict = dict(existing_case)
                    case_dict["source"] = "feedback"
                    case_dict.pop("case_id", None)

        elif source_type == "agent_run":
            if feedback.get("replay_id") and self.replay_service:
                snapshot = self.replay_service.get_snapshot(feedback["replay_id"])
                if snapshot:
                    case = build_eval_case_from_replay(snapshot)
                    case_dict = case.to_dict()

        if case_dict is None:
            evidence = feedback.get("evidence") or {}
            agent_name = feedback.get("agent_name", "unknown")
            case_dict = {
                "agent_name": agent_name,
                "title": feedback.get("title", ""),
                "description": feedback.get("description", ""),
                "tags": list(feedback.get("tags") or []),
                "source": "feedback",
                "input": evidence.get("input") or {},
                "mock_context": evidence.get("mock_context") or {},
                "mock_tool_outputs": evidence.get("mock_tool_outputs") or {},
                "expected_output_fields": [],
                "forbidden_behavior": [],
                "metadata": {"feedback_id": feedback_id, "source_type": source_type, "evidence": evidence},
            }

        payload = payload or {}
        if payload.get("title"):
            case_dict["title"] = payload["title"]
        if "enabled" in payload:
            case_dict["enabled"] = payload["enabled"]
        else:
            case_dict["enabled"] = True

        case_dict["case_id"] = new_eval_case_id(case_dict.get("agent_name", "unknown"))
        metadata = dict(case_dict.get("metadata") or {})
        metadata["created_from_feedback_id"] = feedback_id
        case_dict["metadata"] = metadata
        case_dict.setdefault("tags", [])
        if "bad_case" not in case_dict["tags"]:
            case_dict["tags"].append("bad_case")

        case = EvalCase.from_dict(case_dict)
        saved = self.case_repository.save_case(case.to_dict())

        feedback["status"] = "converted"
        feedback["converted_case_id"] = case.case_id
        feedback["updated_at"] = utc_now_iso()
        self.feedback_repository.save_feedback(feedback)

        return saved

    def create_feedback_from_eval_run_failures(self, eval_run_id: str) -> dict:
        if self.feedback_repository is None:
            raise ValueError("Feedback repository not configured")
        run = self.run_repository.get_run(eval_run_id)
        if run is None:
            raise ValueError("Eval run not found")

        results = run.get("results") or []
        existing_feedbacks = self.feedback_repository.list_feedback(eval_run_id=eval_run_id, limit=10000)
        existing_keys = {
            (f.get("eval_run_id"), f.get("result_case_id") or f.get("case_id"))
            for f in existing_feedbacks
        }

        created = 0
        skipped = 0
        for result in results:
            status_val = result.get("status", "")
            if status_val in {"passed"}:
                continue
            case_id = result.get("case_id", "")
            if (eval_run_id, case_id) in existing_keys:
                skipped += 1
                continue
            checks = result.get("checks") or []
            failed_checks = [c.get("check_name", "") for c in checks if c.get("passed") is False]
            metadata = result.get("metadata") or {}
            issue_type = "other"
            if "required_fields" in failed_checks or "schema_validation" in failed_checks:
                issue_type = "format_error"
            elif "forbidden_behavior" in failed_checks:
                issue_type = "unsafe_investment_advice"
            elif "data_limitations" in failed_checks:
                issue_type = "missing_risk"

            feedback = BadCaseFeedback(
                feedback_id=new_feedback_id(),
                source_type="eval_result",
                source_id=f"{eval_run_id}:{case_id}",
                title=f"Eval failure: {case_id}",
                agent_name=result.get("agent_name", ""),
                issue_type=issue_type,
                severity=metadata.get("severity", "medium"),
                category=metadata.get("category", ""),
                tags=["auto_generated", "eval_failure"],
                eval_run_id=eval_run_id,
                case_id=case_id,
                result_case_id=case_id,
                evidence={
                    "status": status_val,
                    "score": result.get("score", 0),
                    "max_score": result.get("max_score", 0),
                    "failed_checks": failed_checks,
                    "error_code": result.get("error_code"),
                    "error_message": result.get("error_message"),
                    "checks": checks,
                },
            )
            self.feedback_repository.save_feedback(feedback.to_dict())
            created += 1

        return {"created": created, "skipped": skipped, "total_failures": created + skipped}

    def get_eval_coverage(
        self,
        *,
        agent_name: str | None = None,
        hours: int = 24 * 30,
        limit: int = 1000,
        include_disabled: bool = True,
    ) -> dict:
        cases = self.list_cases(agent_name=agent_name, limit=limit)
        if not include_disabled:
            cases = [c for c in cases if _case_is_enabled(c)]

        runs = self.run_repository.list_runs(hours=hours, limit=limit)

        case_map: dict[str, dict] = {}
        for c in cases:
            cid = c.get("case_id", "")
            if cid:
                case_map[cid] = c

        # Build per-case result occurrence stats from recent EvalRuns.
        case_run_stats: dict[str, dict] = {}
        agent_eval_run_ids: dict[str, set[str]] = {}
        for run in runs:
            run_id = run.get("eval_run_id")
            run_ts = run.get("finished_at") or run.get("started_at") or ""
            for result in run.get("results") or []:
                cid = result.get("case_id", "")
                if not cid:
                    continue
                case = case_map.get(cid)
                if case is not None:
                    result_agent = case.get("agent_name")
                    if result_agent and run_id:
                        agent_eval_run_ids.setdefault(result_agent, set()).add(run_id)
                entry = case_run_stats.setdefault(cid, {
                    "recent_run_count": 0,
                    "recent_pass_count": 0,
                    "recent_failed_count": 0,
                })
                if run_ts > (entry.get("last_evaluated_at") or ""):
                    entry.update({
                        "last_eval_run_id": run_id,
                        "last_status": result.get("status"),
                        "last_score": result.get("score"),
                        "last_max_score": result.get("max_score"),
                        "last_evaluated_at": run_ts,
                    })
                entry["recent_run_count"] = entry.get("recent_run_count", 0) + 1
                status_val = result.get("status", "")
                if status_val == "passed":
                    entry["recent_pass_count"] = entry.get("recent_pass_count", 0) + 1
                elif status_val in {"failed", "error", "warning"}:
                    entry["recent_failed_count"] = entry.get("recent_failed_count", 0) + 1

        # Build per-run case sets for never_evaluated detection
        evaluated_case_ids: set[str] = set()
        for run in runs:
            for result in run.get("results") or []:
                cid = result.get("case_id", "")
                if cid:
                    evaluated_case_ids.add(cid)

        # Build case_coverage rows
        case_coverage: list[dict] = []
        for c in cases:
            cid = c.get("case_id", "")
            stats = case_run_stats.get(cid, {})
            tags = c.get("tags") or []
            case_coverage.append({
                "case_id": cid,
                "agent_name": c.get("agent_name"),
                "title": c.get("title"),
                "enabled": c.get("enabled", True),
                "severity": c.get("severity") or "medium",
                "category": c.get("category") or "uncategorized",
                "tags": tags,
                "source": c.get("source") or "unknown",
                "judge_enabled": c.get("judge_enabled", False),
                "eval_scope": c.get("eval_scope") or "agent",
                "node_name": c.get("node_name"),
                "prompt_key": c.get("prompt_key"),
                "model": c.get("model"),
                "last_eval_run_id": stats.get("last_eval_run_id"),
                "last_status": stats.get("last_status"),
                "last_score": stats.get("last_score"),
                "last_max_score": stats.get("last_max_score"),
                "last_evaluated_at": stats.get("last_evaluated_at"),
                "recent_run_count": stats.get("recent_run_count", 0),
                "recent_pass_count": stats.get("recent_pass_count", 0),
                "recent_failed_count": stats.get("recent_failed_count", 0),
                "never_evaluated": cid not in evaluated_case_ids,
            })

        # Aggregation helpers
        def _agg_agent(rows: list[dict]) -> list[dict]:
            buckets: dict[str, dict] = {}
            for row in rows:
                aname = row.get("agent_name") or "unknown"
                b = buckets.setdefault(aname, {
                    "agent_name": aname, "case_count": 0, "enabled_case_count": 0,
                    "disabled_case_count": 0, "judge_case_count": 0,
                    "recent_eval_run_count": 0, "recent_pass_count": 0,
                    "recent_failed_count": 0, "recent_error_count": 0,
                    "high_case_count": 0, "critical_case_count": 0,
                    "high_critical_failure_count": 0, "never_evaluated_case_count": 0,
                    "_evaluated_result_count": 0,
                })
                b["case_count"] += 1
                if row.get("enabled", True):
                    b["enabled_case_count"] += 1
                else:
                    b["disabled_case_count"] += 1
                if row.get("judge_enabled"):
                    b["judge_case_count"] += 1
                sev = row.get("severity", "medium")
                if sev == "high":
                    b["high_case_count"] += 1
                elif sev == "critical":
                    b["critical_case_count"] += 1
                if row.get("never_evaluated"):
                    b["never_evaluated_case_count"] += 1
                stats = case_run_stats.get(row.get("case_id", ""), {})
                if stats.get("recent_run_count", 0) > 0:
                    b["_evaluated_result_count"] += stats.get("recent_run_count", 0)
                    b["recent_pass_count"] += stats.get("recent_pass_count", 0)
                    b["recent_failed_count"] += stats.get("recent_failed_count", 0)
                    ls = stats.get("last_status", "")
                    if ls in {"failed", "error"}:
                        b["recent_error_count"] += 1
                    if ls in {"failed", "error", "warning"} and sev in {"high", "critical"}:
                        b["high_critical_failure_count"] += 1

            result: list[dict] = []
            for b in buckets.values():
                evaled = b.pop("_evaluated_result_count")
                b["recent_eval_run_count"] = len(agent_eval_run_ids.get(b["agent_name"], set()))
                b["recent_pass_rate"] = (b["recent_pass_count"] / evaled) if evaled > 0 else None
                result.append(b)
            return sorted(result, key=lambda x: x["agent_name"])

        def _agg_group(rows: list[dict], group_key: str, extra_fields: list[str] | None = None) -> list[dict]:
            buckets: dict[tuple, dict] = {}
            for row in rows:
                aname = row.get("agent_name") or "unknown"
                gval = row.get(group_key) or ("uncategorized" if group_key == "category" else "untagged" if group_key == "tags" else "unknown")
                if group_key == "tags":
                    tag_list = row.get("tags") or ["untagged"]
                    for tag in tag_list:
                        key = (aname, tag)
                        b = buckets.setdefault(key, {
                            "agent_name": aname, "tag": tag,
                            "case_count": 0, "enabled_case_count": 0,
                            "recent_pass_count": 0, "_evaluated_result_count": 0,
                        })
                        b["case_count"] += 1
                        if row.get("enabled", True):
                            b["enabled_case_count"] += 1
                        stats = case_run_stats.get(row.get("case_id", ""), {})
                        if stats.get("recent_run_count", 0) > 0:
                            b["_evaluated_result_count"] += stats.get("recent_run_count", 0)
                            b["recent_pass_count"] += stats.get("recent_pass_count", 0)
                else:
                    key = (aname, gval)
                    b = buckets.setdefault(key, {
                        "agent_name": aname, group_key: gval,
                        "case_count": 0, "enabled_case_count": 0,
                        "recent_pass_count": 0, "recent_failed_count": 0,
                        "_evaluated_result_count": 0,
                    })
                    if extra_fields:
                        for f in extra_fields:
                            b.setdefault(f, 0)
                    b["case_count"] += 1
                    if row.get("enabled", True):
                        b["enabled_case_count"] += 1
                    sev = row.get("severity", "medium")
                    if extra_fields and "high_case_count" in extra_fields and sev == "high":
                        b["high_case_count"] += 1
                    if extra_fields and "critical_case_count" in extra_fields and sev == "critical":
                        b["critical_case_count"] += 1
                    stats = case_run_stats.get(row.get("case_id", ""), {})
                    if stats.get("recent_run_count", 0) > 0:
                        b["_evaluated_result_count"] += stats.get("recent_run_count", 0)
                        b["recent_pass_count"] += stats.get("recent_pass_count", 0)
                        b["recent_failed_count"] += stats.get("recent_failed_count", 0)

            result: list[dict] = []
            for b in buckets.values():
                evaled = b.pop("_evaluated_result_count")
                b["recent_pass_rate"] = (b["recent_pass_count"] / evaled) if evaled > 0 else None
                result.append(b)
            return sorted(result, key=lambda x: (x.get("agent_name", ""), str(x.get(group_key, "") if group_key != "tags" else x.get("tag", ""))))

        def _agg_source(rows: list[dict]) -> list[dict]:
            buckets: dict[str, dict] = {}
            for row in rows:
                src = row.get("source") or "unknown"
                b = buckets.setdefault(src, {"source": src, "case_count": 0, "enabled_case_count": 0})
                b["case_count"] += 1
                if row.get("enabled", True):
                    b["enabled_case_count"] += 1
            return sorted(buckets.values(), key=lambda x: x["source"])

        agents_seen = {c.get("agent_name") for c in cases if c.get("agent_name")}
        never_evaluated_count = sum(1 for c in case_coverage if c.get("never_evaluated"))
        evaluated_count = len(case_coverage) - never_evaluated_count

        by_agent = _agg_agent(case_coverage)

        summary = {
            "case_count": len(cases),
            "enabled_case_count": sum(1 for c in cases if c.get("enabled", True) is not False),
            "disabled_case_count": sum(1 for c in cases if c.get("enabled", True) is False),
            "agent_count": len(agents_seen),
            "judge_case_count": sum(1 for c in cases if c.get("judge_enabled")),
            "bad_case_source_count": sum(1 for c in cases if c.get("source") == "feedback"),
            "replay_source_count": sum(1 for c in cases if c.get("source") == "replay"),
            "manual_source_count": sum(1 for c in cases if c.get("source") == "manual"),
            "recent_eval_run_count": len(runs),
            "recent_evaluated_case_count": evaluated_count,
            "never_evaluated_case_count": never_evaluated_count,
        }

        coverage = {
            "summary": summary,
            "by_agent": by_agent,
            "by_agent_category": _agg_group(case_coverage, "category", extra_fields=["high_case_count", "critical_case_count"]),
            "by_agent_severity": _agg_group(case_coverage, "severity"),
            "by_agent_tag": _agg_group(case_coverage, "tags"),
            "by_source": _agg_source(case_coverage),
            "case_coverage": case_coverage,
        }
        gaps = build_coverage_gaps(coverage)
        recommendations = build_coverage_recommendations(gaps)
        coverage["gaps"] = gaps
        coverage["recommendations"] = recommendations
        return coverage

    def _summary(self, results: list[dict]) -> dict:
        count = len(results)
        total_score = sum(float(item.get("score") or 0) for item in results)
        max_score = sum(float(item.get("max_score") or 0) for item in results)

        status_counts = _status_counts(results)
        severity_counts = _metadata_counts(results, "severity")
        category_counts = _metadata_counts(results, "category", empty="uncategorized")
        check_counts, failed_check_counts = _check_counts(results)
        high_priority_failure_count = sum(
            1 for item in results
            if item.get("status") in {"warning", "failed", "error"}
            and _result_includes_severity(item, {"high", "critical", "fatal"})
        )
        critical_failure_count = sum(
            1 for item in results
            if item.get("status") in {"warning", "failed", "error"}
            and _result_includes_severity(item, {"critical", "fatal"})
        )

        return {
            "case_count": count,
            "passed_count": status_counts.get("passed", 0),
            "warning_count": status_counts.get("warning", 0),
            "failed_count": status_counts.get("failed", 0),
            "error_count": status_counts.get("error", 0),
            "avg_score": total_score / count if count else 0,
            "max_score": max_score,
            "pass_rate": status_counts.get("passed", 0) / count if count else 0,
            "by_agent": _bucket(results, "agent_name"),
            "status_counts": status_counts,
            "severity_counts": severity_counts,
            "category_counts": category_counts,
            "check_counts": check_counts,
            "failed_check_counts": failed_check_counts,
            "high_priority_failure_count": high_priority_failure_count,
            "critical_failure_count": critical_failure_count,
            "score_rate": total_score / max_score if max_score > 0 else 0,
            "failed_cases": _failed_cases(results),
        }


def _bucket(items: list[dict], key: str) -> dict[str, dict[str, int]]:
    buckets: dict[str, dict[str, int]] = {}
    for item in items:
        name = str(item.get(key) or "unknown")
        bucket = buckets.setdefault(name, {"case_count": 0, "passed_count": 0, "warning_count": 0, "failed_count": 0, "error_count": 0})
        bucket["case_count"] += 1
        status = item.get("status")
        if status in {"passed", "warning", "failed", "error"}:
            bucket[f"{status}_count"] += 1
    return buckets


def _status_counts(results: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in results:
        status = item.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _metadata_counts(results: list[dict], key: str, *, empty: str = "uncategorized") -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in results:
        metadata = item.get("metadata") or {}
        value = metadata.get(key) or empty
        counts[value] = counts.get(value, 0) + 1
    return counts


def _result_includes_severity(result: dict, severities: set[str]) -> bool:
    """判断 result 是否触发了给定 severity 集合的检查或 metadata 标记。

    - metadata.severity in severities → True
    - 存在任一 failed check 且其 severity in severities → True
    """
    metadata = result.get("metadata") or {}
    case_sev = metadata.get("severity")
    if case_sev in severities:
        return True
    for check in result.get("checks") or []:
        if check.get("passed") is False and check.get("severity") in severities:
            return True
    return False


def _check_counts(results: list[dict]) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    check_counts: dict[str, dict[str, int]] = {}
    failed_check_counts: dict[str, int] = {}
    for item in results:
        checks = item.get("checks") or []
        for check in checks:
            name = check.get("check_name", "unknown")
            passed = check.get("passed")
            if name not in check_counts:
                check_counts[name] = {"passed": 0, "failed": 0, "warning": 0}
            if passed is True:
                check_counts[name]["passed"] += 1
            elif passed is False:
                check_counts[name]["failed"] += 1
                failed_check_counts[name] = failed_check_counts.get(name, 0) + 1
            else:
                check_counts[name]["warning"] += 1
    return check_counts, failed_check_counts


def _failed_cases(results: list[dict], limit: int = 50) -> list[dict]:
    failed = []
    for item in results:
        status = item.get("status", "")
        if status in {"warning", "failed", "error"}:
            checks = item.get("checks") or []
            failed_checks = [c.get("check_name", "") for c in checks if c.get("passed") is False]
            metadata = item.get("metadata") or {}
            message = item.get("error_message") or ""
            if not message:
                first_failed = next((c for c in checks if c.get("passed") is False), None)
                if first_failed:
                    message = first_failed.get("message", "")
            failed.append({
                "case_id": item.get("case_id", ""),
                "agent_name": item.get("agent_name", ""),
                "status": status,
                "severity": metadata.get("severity", "medium"),
                "category": metadata.get("category", ""),
                "score": item.get("score", 0),
                "max_score": item.get("max_score", 0),
                "failed_checks": failed_checks,
                "error_code": item.get("error_code"),
                "message": message,
            })
    return failed[:limit]


_STATUS_RANK = {"passed": 0, "warning": 1, "failed": 2, "error": 3}


def _result_status_rank(status: str | None) -> int:
    return _STATUS_RANK.get(status, 0)


def _result_failed_checks(result: dict) -> list[str]:
    return [c.get("check_name", "") for c in (result.get("checks") or []) if c.get("passed") is False]


def _result_severity(result: dict) -> str:
    return (result.get("metadata") or {}).get("severity", "medium")


def _result_category(result: dict) -> str:
    return (result.get("metadata") or {}).get("category", "uncategorized")


def _build_case_diff(baseline: dict, candidate: dict) -> dict:
    b_checks = set(_result_failed_checks(baseline))
    c_checks = set(_result_failed_checks(candidate))
    return {
        "case_id": baseline.get("case_id", ""),
        "agent_name": baseline.get("agent_name", ""),
        "baseline_status": baseline.get("status", ""),
        "candidate_status": candidate.get("status", ""),
        "baseline_score": baseline.get("score", 0),
        "candidate_score": candidate.get("score", 0),
        "baseline_max_score": baseline.get("max_score", 0),
        "candidate_max_score": candidate.get("max_score", 0),
        "score_delta": (candidate.get("score", 0) or 0) - (baseline.get("score", 0) or 0),
        "severity": _result_severity(candidate),
        "category": _result_category(candidate),
        "baseline_failed_checks": sorted(b_checks),
        "candidate_failed_checks": sorted(c_checks),
        "new_failed_checks": sorted(c_checks - b_checks),
        "fixed_failed_checks": sorted(b_checks - c_checks),
        "message": (candidate.get("error_message") or ""),
    }


def _build_delta(baseline_results: list[dict], candidate_results: list[dict], key: str) -> dict[str, dict[str, int]]:
    def count_failed_by(results: list[dict], key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in results:
            if r.get("status") in {"warning", "failed", "error"}:
                value = (r.get("metadata") or {}).get(key) or "uncategorized"
                counts[value] = counts.get(value, 0) + 1
        return counts

    b_counts = count_failed_by(baseline_results, key)
    c_counts = count_failed_by(candidate_results, key)
    all_keys = set(b_counts.keys()) | set(c_counts.keys())
    delta: dict[str, dict[str, int]] = {}
    for k in sorted(all_keys):
        b = b_counts.get(k, 0)
        c = c_counts.get(k, 0)
        delta[k] = {"baseline_failed": b, "candidate_failed": c, "delta": c - b}
    return delta


def _build_check_delta(baseline_results: list[dict], candidate_results: list[dict]) -> dict[str, dict[str, int]]:
    def count_failed_checks(results: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in results:
            for check in (r.get("checks") or []):
                if check.get("passed") is False:
                    name = check.get("check_name", "unknown")
                    counts[name] = counts.get(name, 0) + 1
        return counts

    b_counts = count_failed_checks(baseline_results)
    c_counts = count_failed_checks(candidate_results)
    all_keys = set(b_counts.keys()) | set(c_counts.keys())
    delta: dict[str, dict[str, int]] = {}
    for k in sorted(all_keys):
        b = b_counts.get(k, 0)
        c = c_counts.get(k, 0)
        delta[k] = {"baseline_failed": b, "candidate_failed": c, "delta": c - b}
    return delta


# ── Coverage Gap & Recommendation ─────────────────────────────────────


def build_coverage_gaps(coverage: dict) -> list[dict]:
    gaps: list[dict] = []
    by_agent = coverage.get("by_agent") or []
    case_coverage = coverage.get("case_coverage") or []

    for agent_row in by_agent:
        aname = agent_row.get("agent_name", "unknown")
        enabled = agent_row.get("enabled_case_count", 0)
        high = agent_row.get("high_case_count", 0)
        critical = agent_row.get("critical_case_count", 0)
        never = agent_row.get("never_evaluated_case_count", 0)
        pass_rate = agent_row.get("recent_pass_rate")
        hc_failures = agent_row.get("high_critical_failure_count", 0)

        if enabled == 0:
            gaps.append(_gap(aname, "no_enabled_cases", "critical", "coverage",
                             f"{aname} 没有任何启用的 Eval Case",
                             "该 Agent 没有任何启用的 Eval Case，无法进行有效回归。",
                             {"enabled_case_count": 0},
                             "新增至少 1 个 enabled Eval Case。"))

        if high == 0 and enabled > 0:
            gaps.append(_gap(aname, "no_high_cases", "medium", "coverage",
                             f"{aname} 缺少 high Eval Case",
                             "缺少 high severity 用例，无法覆盖高风险但非致命场景。",
                             {"high_case_count": 0, "enabled_case_count": enabled},
                             "新增至少 1 个 high severity 的 Eval Case。"))

        if critical == 0 and enabled > 0:
            gaps.append(_gap(aname, "no_critical_cases", "high", "coverage",
                             f"{aname} 缺少 critical Eval Case",
                             "缺少 critical severity 用例，无法保护最高风险场景。",
                             {"critical_case_count": 0, "enabled_case_count": enabled},
                             "新增至少 1 个 critical severity 的 Eval Case。"))

        if pass_rate is not None and pass_rate < 0.9:
            sev = "critical" if pass_rate < 0.8 else "high"
            gaps.append(_gap(aname, "low_recent_pass_rate", sev, "quality",
                             f"{aname} 最近通过率过低 ({pass_rate:.1%})",
                             f"该 Agent 最近通过率 {pass_rate:.1%}，可能存在退化。",
                             {"recent_pass_rate": pass_rate},
                             "修复失败用例并运行回归评测。"))

        if hc_failures > 0:
            gaps.append(_gap(aname, "high_critical_failures", "critical", "quality",
                             f"{aname} 有 {hc_failures} 个 high/critical 失败",
                             "存在 high 或 critical severity 的用例运行失败，需要优先修复。",
                             {"high_critical_failure_count": hc_failures},
                             "优先修复这些失败用例。"))

        if never > 0:
            gaps.append(_gap(aname, "never_evaluated_cases", "medium", "coverage",
                             f"{aname} 有 {never} 个 Case 在统计窗口内未运行",
                             "存在从未被评测运行的用例，无法确认其是否有效。",
                             {"never_evaluated_case_count": never},
                             "运行该 Agent 的回归评测。"))

    # Check regression tag coverage
    agent_tags: dict[str, set[str]] = {}
    for row in case_coverage:
        if not row.get("enabled", True):
            continue
        aname = row.get("agent_name") or "unknown"
        tags = set(row.get("tags") or [])
        agent_tags.setdefault(aname, set()).update(tags)
    for agent_row in by_agent:
        aname = agent_row.get("agent_name", "unknown")
        if agent_row.get("enabled_case_count", 0) > 0 and "regression" not in agent_tags.get(aname, set()):
            gaps.append(_gap(aname, "no_regression_cases", "high", "coverage",
                             f"{aname} 缺少 regression 回归集",
                             "该 Agent 没有专门的 regression 回归集，Prompt 或代码变更后难以一键验证。",
                             {"enabled_case_count": agent_row.get("enabled_case_count", 0)},
                             "为该 Agent 的关键用例添加 regression tag。"))

    # Check judge for critical cases
    agent_critical_no_judge: dict[str, int] = {}
    for row in case_coverage:
        if not row.get("enabled", True):
            continue
        if row.get("severity") == "critical" and not row.get("judge_enabled"):
            aname = row.get("agent_name") or "unknown"
            agent_critical_no_judge[aname] = agent_critical_no_judge.get(aname, 0) + 1
    for aname, count in agent_critical_no_judge.items():
        gaps.append(_gap(aname, "judge_not_configured_for_critical", "medium", "coverage",
                         f"{aname} 有 {count} 个 critical Case 未启用 LLM Judge",
                         "critical case 建议启用 LLM Judge，补充规则检查无法覆盖的推理质量评估。",
                         {"critical_no_judge_count": count},
                         "为 critical severity 的用例启用 LLM Judge。"))

    return sorted(gaps, key=lambda g: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(g.get("severity", "low"), 4))


def build_coverage_recommendations(gaps: list[dict]) -> list[dict]:
    recommendations: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    action_map = {
        "no_enabled_cases": "create_eval_case",
        "no_high_cases": "create_eval_case",
        "no_critical_cases": "create_eval_case",
        "no_regression_cases": "add_regression_tag",
        "low_recent_pass_rate": "fix_failed_cases",
        "high_critical_failures": "fix_failed_cases",
        "never_evaluated_cases": "run_agent_regression",
        "uncategorized_cases": "categorize_cases",
        "untagged_cases": "tag_cases",
        "judge_not_configured_for_critical": "enable_judge",
    }

    for gap in gaps:
        aname = gap.get("agent_name") or "unknown"
        gap_type = gap.get("gap_type", "")
        action_type = action_map.get(gap_type, "review_coverage")
        dedup_key = (aname, action_type, gap_type)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        rec_id = f"rec_{aname}_{gap_type}"
        recommendations.append({
            "recommendation_id": rec_id,
            "agent_name": aname,
            "priority": gap.get("severity", "medium"),
            "title": gap.get("suggested_action", f"处理 {aname} 的覆盖缺口"),
            "description": gap.get("description", ""),
            "action_type": action_type,
            "related_gap_ids": [gap.get("gap_id", "")],
            "metadata": {},
        })

    return sorted(recommendations, key=lambda r: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(r.get("priority", "low"), 4))


def _gap(agent_name: str, gap_type: str, severity: str, category: str,
         title: str, description: str, evidence: dict, suggested_action: str) -> dict:
    return {
        "gap_id": f"gap_{agent_name}_{gap_type}",
        "agent_name": agent_name,
        "gap_type": gap_type,
        "severity": severity,
        "category": category,
        "title": title,
        "description": description,
        "evidence": evidence,
        "suggested_action": suggested_action,
    }
