from __future__ import annotations

from collections import Counter
from typing import Any

from app.agents.eval_checks import run_eval_checks
from app.agents.eval_failure_mining import (
    SEVERITY_ORDER,
    FailureMiningRun,
    build_eval_case_from_scenario_for_mining,
    classify_failure,
    finalize_failure_item,
    new_failure_mining_run_id,
    utc_now_iso,
)
from app.agents.eval_judge import AgentEvalJudgeService
from app.agents.eval_simulation_scenarios import get_synthetic_scenario


class SyntheticFailureMiningService:
    def __init__(
        self,
        *,
        failure_repository: Any,
        simulation_repository: Any,
        judge_service: AgentEvalJudgeService | None = None,
    ) -> None:
        self.failure_repository = failure_repository
        self.simulation_repository = simulation_repository
        self.judge_service = judge_service or AgentEvalJudgeService(llm_client=None)

    def mine_simulation_run(
        self,
        simulation_run_id: str,
        *,
        include_dry_run_results: bool = False,
        include_judge: bool = False,
        judge_model_config: dict | None = None,
        min_severity: str | None = None,
        max_failures: int = 100,
        deduplicate: bool = True,
        name: str | None = None,
    ) -> dict[str, Any]:
        simulation_run = self.simulation_repository.get_run(simulation_run_id)
        if simulation_run is None:
            raise ValueError("Simulation run not found")
        simulation_results = self.simulation_repository.list_results(simulation_run_id, limit=10000)
        failure_mining_run_id = new_failure_mining_run_id()
        run = FailureMiningRun(
            failure_mining_run_id=failure_mining_run_id,
            simulation_run_id=simulation_run_id,
            name=name or f"Failure mining - {simulation_run_id}",
            status="running",
            config={
                "include_judge": include_judge,
                "judge_model_config": judge_model_config or {},
                "min_severity": min_severity,
                "max_failures": max_failures,
                "deduplicate": deduplicate,
                "include_dry_run_results": include_dry_run_results,
            },
            metadata={"stage": "p3_5_stage_03", "source": "synthetic_failure_mining"},
        ).to_dict()
        self.failure_repository.save_failure_mining_run(run)

        seeds: list[dict[str, Any]] = []
        evaluated_count = 0
        skipped_dry_run_result_count = 0
        for result in simulation_results:
            if not include_dry_run_results and _is_dry_run_or_fake_result(result):
                skipped_dry_run_result_count += 1
                continue
            scenario = get_synthetic_scenario(result.get("scenario_id") or "")
            if scenario is None:
                continue
            case = build_eval_case_from_scenario_for_mining(scenario)
            output = result.get("output") or {}
            checks = [check.to_dict() for check in run_eval_checks(output, case)]
            judge_result = None
            if include_judge:
                judge_result = self.judge_service.judge_correctness(case=case.to_dict(), output=output)
            if result.get("status") in {"passed", "failed", "error", "skipped"}:
                evaluated_count += 1
            seeds.extend(classify_failure(
                scenario=scenario,
                simulation_result=result,
                checks=checks,
                judge_result=judge_result,
            ))

        if deduplicate:
            seeds, deduplicated_count = self._deduplicate(seeds)
        else:
            deduplicated_count = 0
        if min_severity:
            seeds = [seed for seed in seeds if SEVERITY_ORDER.get(seed.get("severity"), 0) >= SEVERITY_ORDER.get(min_severity, 1)]

        failures = [
            finalize_failure_item(seed, failure_mining_run_id=failure_mining_run_id)
            for seed in seeds
        ]
        failures.sort(key=lambda item: item["conversion_priority"], reverse=True)
        failures = failures[: max(1, min(int(max_failures), 500))]
        for item in failures:
            self.failure_repository.save_failure_item(item)

        summary = self._build_summary(
            simulation_results=simulation_results,
            evaluated_count=evaluated_count,
            failures=failures,
            deduplicated_count=deduplicated_count,
            include_judge=include_judge,
            include_dry_run_results=include_dry_run_results,
            skipped_dry_run_result_count=skipped_dry_run_result_count,
        )
        run["agent_names"] = sorted(summary.get("by_agent") or {})
        run["status"] = "completed"
        run["finished_at"] = utc_now_iso()
        run["summary"] = summary
        self.failure_repository.save_failure_mining_run(run)
        return {"failure_mining_run": run, "failures": failures, "summary": summary}

    def list_failure_mining_runs(
        self,
        *,
        simulation_run_id: str | None = None,
        agent_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return self.failure_repository.list_failure_mining_runs(
            simulation_run_id=simulation_run_id,
            agent_name=agent_name,
            status=status,
            limit=limit,
        )

    def get_failure_mining_run_with_failures(self, failure_mining_run_id: str, *, limit: int = 1000) -> dict | None:
        run = self.failure_repository.get_failure_mining_run(failure_mining_run_id)
        if run is None:
            return None
        failures = self.failure_repository.list_failure_items(failure_mining_run_id=failure_mining_run_id, limit=limit)
        return {"failure_mining_run": run, "failures": failures, "summary": run.get("summary") or {}}

    def list_failure_items(self, **kwargs: Any) -> dict[str, Any]:
        items = self.failure_repository.list_failure_items(**kwargs)
        return {"items": items, "summary": self._failure_list_summary(items)}

    def get_failure_item(self, failure_id: str) -> dict | None:
        return self.failure_repository.get_failure_item(failure_id)

    def _deduplicate(self, seeds: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        buckets: dict[str, dict] = {}
        duplicate_count = 0
        for seed in seeds:
            key = seed["duplicate_key"]
            existing = buckets.get(key)
            if existing is None:
                buckets[key] = seed
                continue
            duplicate_count += 1
            existing["metadata"]["duplicate_count"] = int(existing["metadata"].get("duplicate_count", 1)) + 1
            existing["evidence"].setdefault("duplicates", []).append({
                "failure_id": seed["failure_id"],
                "simulation_result_id": seed["simulation_result_id"],
            })
            if SEVERITY_ORDER[seed["severity"]] > SEVERITY_ORDER[existing["severity"]]:
                seed["metadata"]["duplicate_count"] = existing["metadata"]["duplicate_count"]
                seed["evidence"]["duplicates"] = existing["evidence"].get("duplicates", [])
                buckets[key] = seed
        return list(buckets.values()), duplicate_count

    def _build_summary(
        self,
        *,
        simulation_results: list[dict],
        evaluated_count: int,
        failures: list[dict],
        deduplicated_count: int,
        include_judge: bool,
        include_dry_run_results: bool,
        skipped_dry_run_result_count: int,
    ) -> dict[str, Any]:
        by_severity = Counter(item["severity"] for item in failures)
        failed_dimensions = Counter()
        tags = Counter()
        missing_risk_control_subtypes = Counter()
        for item in failures:
            failed_dimensions.update(item.get("failed_dimensions") or [])
            tags.update(item.get("failure_tags") or [])
            if item.get("failure_type") == "missing_risk_control":
                missing_risk_control_subtypes.update([(item.get("metadata") or {}).get("failure_subtype") or "unknown"])
        return {
            "simulation_result_count": len(simulation_results),
            "evaluated_result_count": evaluated_count,
            "failure_count": len(failures),
            "critical_count": by_severity.get("critical", 0),
            "high_count": by_severity.get("high", 0),
            "medium_count": by_severity.get("medium", 0),
            "low_count": by_severity.get("low", 0),
            "by_agent": dict(Counter(item["agent_name"] for item in failures)),
            "by_failure_type": dict(Counter(item["failure_type"] for item in failures)),
            "missing_risk_control_subtypes": dict(missing_risk_control_subtypes),
            "by_failed_dimension": dict(failed_dimensions),
            "top_failure_tags": dict(tags.most_common(20)),
            "suggested_eval_case_count": sum(1 for item in failures if item.get("should_convert_to_eval_case")),
            "deduplicated_count": deduplicated_count,
            "include_judge": include_judge,
            "include_dry_run_results": include_dry_run_results,
            "skipped_dry_run_result_count": skipped_dry_run_result_count,
        }

    def _failure_list_summary(self, failures: list[dict]) -> dict[str, Any]:
        return {
            "failure_count": len(failures),
            "by_agent": dict(Counter(item["agent_name"] for item in failures)),
            "by_failure_type": dict(Counter(item["failure_type"] for item in failures)),
            "suggested_eval_case_count": sum(1 for item in failures if item.get("should_convert_to_eval_case")),
        }


def _is_dry_run_or_fake_result(result: dict) -> bool:
    metadata = result.get("metadata") or {}
    executor_mode = metadata.get("executor_mode")
    if metadata.get("dry_run") is True:
        return True
    if executor_mode in {"dry_run", "fake"}:
        return True
    if metadata.get("agent_called") is False and executor_mode != "real":
        return True
    return False
