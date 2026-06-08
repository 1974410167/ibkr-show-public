from __future__ import annotations

from collections import Counter
import threading
from typing import Any

from app.agents.eval_simulation_runner import (
    SyntheticSimulationResult,
    SyntheticSimulationRun,
    new_simulation_result_id,
    new_simulation_run_id,
    utc_now_iso,
)
from app.agents.eval_simulation_scenarios import (
    filter_synthetic_scenarios,
    get_synthetic_scenario,
)
from app.services.eval_simulation_executors import (
    DryRunSimulationAgentExecutor,
    FakeSimulationAgentExecutor,
    RealSimulationAgentExecutor,
    SimulationAgentExecutor,
)


VALID_EXECUTOR_MODES = {"auto", "fake", "real"}


class SyntheticSimulationService:
    def __init__(
        self,
        repository: Any,
        *,
        fake_executor: SimulationAgentExecutor | None = None,
        real_executor: SimulationAgentExecutor | None = None,
    ) -> None:
        self.repository = repository
        self.fake_executor = fake_executor or FakeSimulationAgentExecutor()
        self.real_executor = real_executor or RealSimulationAgentExecutor()

    def run_scenarios(
        self,
        *,
        scenario_ids: list[str] | None = None,
        agent_name: str | None = None,
        tag: str | None = None,
        severity: str | None = None,
        category: str | None = None,
        limit: int = 20,
        dry_run: bool = False,
        executor_mode: str = "auto",
        name: str | None = None,
    ) -> dict[str, Any]:
        run, scenarios = self._create_run(
            scenario_ids=scenario_ids,
            agent_name=agent_name,
            tag=tag,
            severity=severity,
            category=category,
            limit=limit,
            dry_run=dry_run,
            executor_mode=executor_mode,
            name=name,
            async_run=False,
        )
        return self._execute_run(run, scenarios, dry_run=dry_run, executor_mode=executor_mode)

    def start_scenarios_async(
        self,
        *,
        scenario_ids: list[str] | None = None,
        agent_name: str | None = None,
        tag: str | None = None,
        severity: str | None = None,
        category: str | None = None,
        limit: int = 20,
        dry_run: bool = False,
        executor_mode: str = "auto",
        name: str | None = None,
    ) -> dict[str, Any]:
        run, scenarios = self._create_run(
            scenario_ids=scenario_ids,
            agent_name=agent_name,
            tag=tag,
            severity=severity,
            category=category,
            limit=limit,
            dry_run=dry_run,
            executor_mode=executor_mode,
            name=name,
            async_run=True,
        )
        thread = threading.Thread(
            target=self._execute_run_safely,
            args=(run, scenarios),
            kwargs={"dry_run": dry_run, "executor_mode": executor_mode},
            name=f"synthetic-simulation-{run['simulation_run_id']}",
            daemon=True,
        )
        thread.start()
        run["metadata"]["background_thread_started"] = True
        self.repository.save_run(run)
        return {"simulation_run": run, "results": []}

    def _create_run(
        self,
        *,
        scenario_ids: list[str] | None,
        agent_name: str | None,
        tag: str | None,
        severity: str | None,
        category: str | None,
        limit: int,
        dry_run: bool,
        executor_mode: str,
        name: str | None,
        async_run: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if executor_mode not in VALID_EXECUTOR_MODES:
            raise ValueError(f"Invalid executor_mode: {executor_mode}")
        scenarios = self._select_scenarios(
            scenario_ids=scenario_ids,
            agent_name=agent_name,
            tag=tag,
            severity=severity,
            category=category,
            limit=limit,
        )
        if not scenarios:
            raise ValueError("No synthetic scenarios matched simulation selector")

        simulation_run_id = new_simulation_run_id()
        run = SyntheticSimulationRun(
            simulation_run_id=simulation_run_id,
            name=name or f"Synthetic simulation - {len(scenarios)} scenarios",
            scenario_ids=[scenario["scenario_id"] for scenario in scenarios],
            agent_names=sorted({scenario["agent_name"] for scenario in scenarios}),
            status="running",
            config={
                "scenario_ids": scenario_ids or [],
                "agent_name": agent_name,
                "tag": tag,
                "severity": severity,
                "category": category,
                "limit": limit,
                "dry_run": dry_run,
                "executor_mode": executor_mode,
                "async_run": async_run,
            },
            summary={
                "scenario_count": len(scenarios),
                "executed_count": 0,
                "skipped_count": 0,
                "error_count": 0,
                "by_agent": {},
                "avg_latency_ms": 0,
                "dry_run": dry_run,
                "by_status": {},
                "completed_count": 0,
                "remaining_count": len(scenarios),
            },
            metadata={
                "stage": "p3_5_stage_02",
                "source": "synthetic_simulation",
                "async_run": async_run,
                "current_scenario_id": None,
                "current_scenario_index": None,
                "current_scenario_started_at": None,
                "progress": {
                    "total": len(scenarios),
                    "completed": 0,
                    "remaining": len(scenarios),
                },
            },
        ).to_dict()
        self.repository.save_run(run)
        return run, scenarios

    def _execute_run_safely(
        self,
        run: dict[str, Any],
        scenarios: list[dict[str, Any]],
        *,
        dry_run: bool,
        executor_mode: str,
    ) -> None:
        try:
            self._execute_run(run, scenarios, dry_run=dry_run, executor_mode=executor_mode)
        except Exception as exc:
            latest = self.repository.get_run(run["simulation_run_id"]) or run
            latest["status"] = "failed"
            latest["finished_at"] = utc_now_iso()
            latest.setdefault("metadata", {})
            latest["metadata"]["error_code"] = getattr(exc, "error_code", "SIMULATION_RUN_ERROR")
            latest["metadata"]["error_message"] = str(exc)
            self.repository.save_run(latest)

    def _execute_run(
        self,
        run: dict[str, Any],
        scenarios: list[dict[str, Any]],
        *,
        dry_run: bool,
        executor_mode: str,
    ) -> dict[str, Any]:
        executor = self._select_executor(dry_run=dry_run, executor_mode=executor_mode)
        results: list[dict[str, Any]] = []
        for index, scenario in enumerate(scenarios, start=1):
            self._mark_current_scenario(run, scenario, index=index, total=len(scenarios), completed=len(results))
            try:
                payload = executor.execute(scenario)
            except Exception as exc:
                payload = {
                    "status": "error",
                    "output": {},
                    "latency_ms": 0,
                    "error_code": getattr(exc, "error_code", "EXECUTOR_ERROR"),
                    "error_message": getattr(exc, "message", str(exc)),
                    "metadata": {"executor_mode": executor_mode, "dry_run": dry_run, "agent_called": True},
                }
            result = SyntheticSimulationResult(
                simulation_result_id=new_simulation_result_id(),
                simulation_run_id=run["simulation_run_id"],
                scenario_id=scenario["scenario_id"],
                agent_name=scenario["agent_name"],
                status=payload.get("status") or "error",
                user_question=scenario.get("user_question") or "",
                output=payload.get("output") or {},
                output_summary=payload.get("output_summary") or {},
                run_trace=list(payload.get("run_trace") or []),
                node_outputs=list(payload.get("node_outputs") or []),
                tool_calls=list(payload.get("tool_calls") or []),
                latency_ms=int(payload.get("latency_ms") or 0),
                error_code=payload.get("error_code"),
                error_message=payload.get("error_message"),
                source_run_id=payload.get("source_run_id"),
                source_task_id=payload.get("source_task_id"),
                source_document_id=payload.get("source_document_id"),
                metadata={
                    "scenario": {
                        "title": scenario.get("title"),
                        "category": scenario.get("category"),
                        "severity": scenario.get("severity"),
                        "tags": scenario.get("tags") or [],
                        "scenario_type": (scenario.get("metadata") or {}).get("scenario_type"),
                    },
                    **(payload.get("metadata") or {}),
                },
            ).to_dict()
            self.repository.save_result(result)
            results.append(result)
            self._save_partial_summary(run, results, scenarios, dry_run=dry_run)

        summary = self._build_summary(results, dry_run=dry_run)
        summary["scenario_count"] = len(scenarios)
        summary["completed_count"] = len(results)
        summary["remaining_count"] = 0
        run["status"] = self._run_status_from_summary(summary)
        run["finished_at"] = utc_now_iso()
        run["summary"] = summary
        run.setdefault("metadata", {})
        run["metadata"]["current_scenario_id"] = None
        run["metadata"]["current_scenario_index"] = None
        run["metadata"]["current_scenario_started_at"] = None
        run["metadata"]["progress"] = {
            "total": len(scenarios),
            "completed": len(results),
            "remaining": 0,
        }
        run["results"] = results
        self.repository.save_run(run)
        return {"simulation_run": run, "results": results}

    def list_runs(
        self,
        *,
        agent_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return self.repository.list_runs(agent_name=agent_name, status=status, limit=limit)

    def get_run_with_results(self, simulation_run_id: str, *, limit: int = 1000) -> dict | None:
        run = self.repository.get_run(simulation_run_id)
        if run is None:
            return None
        results = self.repository.list_results(simulation_run_id, limit=limit)
        return {"simulation_run": run, "results": results}

    def get_result(self, simulation_result_id: str) -> dict | None:
        return self.repository.get_result(simulation_result_id)

    def _select_scenarios(
        self,
        *,
        scenario_ids: list[str] | None,
        agent_name: str | None,
        tag: str | None,
        severity: str | None,
        category: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        if scenario_ids:
            scenarios = []
            missing = []
            for scenario_id in scenario_ids:
                scenario = get_synthetic_scenario(scenario_id)
                if scenario is None:
                    missing.append(scenario_id)
                else:
                    scenarios.append(scenario)
            if missing:
                raise ValueError(f"Unknown synthetic scenario_id(s): {', '.join(missing)}")
            if agent_name:
                scenarios = [scenario for scenario in scenarios if scenario["agent_name"] == agent_name]
            if tag:
                scenarios = [scenario for scenario in scenarios if tag in (scenario.get("tags") or [])]
            if severity:
                scenarios = [scenario for scenario in scenarios if scenario.get("severity") == severity]
            if category:
                scenarios = [scenario for scenario in scenarios if scenario.get("category") == category]
            return scenarios[:safe_limit]
        return filter_synthetic_scenarios(
            agent_name=agent_name,
            tag=tag,
            severity=severity,
            category=category,
            limit=safe_limit,
        )

    def _select_executor(self, *, dry_run: bool, executor_mode: str) -> SimulationAgentExecutor:
        if dry_run:
            return DryRunSimulationAgentExecutor()
        if executor_mode == "fake":
            return self.fake_executor
        if executor_mode == "real":
            return self.real_executor
        return self.fake_executor

    def _build_summary(self, results: list[dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
        status_counts = Counter(result.get("status") or "error" for result in results)
        latencies = [int(result.get("latency_ms") or 0) for result in results]
        return {
            "scenario_count": len(results),
            "executed_count": status_counts.get("passed", 0) + status_counts.get("failed", 0),
            "skipped_count": status_counts.get("skipped", 0),
            "error_count": status_counts.get("error", 0),
            "by_agent": dict(Counter(result.get("agent_name") for result in results)),
            "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
            "dry_run": dry_run,
            "by_status": dict(status_counts),
        }

    def _mark_current_scenario(
        self,
        run: dict[str, Any],
        scenario: dict[str, Any],
        *,
        index: int,
        total: int,
        completed: int,
    ) -> None:
        run.setdefault("metadata", {})
        run["metadata"]["current_scenario_id"] = scenario.get("scenario_id")
        run["metadata"]["current_scenario_index"] = index
        run["metadata"]["current_scenario_started_at"] = utc_now_iso()
        run["metadata"]["progress"] = {
            "total": total,
            "completed": completed,
            "remaining": max(0, total - completed),
        }
        run["status"] = "running"
        self.repository.save_run(run)

    def _save_partial_summary(
        self,
        run: dict[str, Any],
        results: list[dict[str, Any]],
        scenarios: list[dict[str, Any]],
        *,
        dry_run: bool,
    ) -> None:
        summary = self._build_summary(results, dry_run=dry_run)
        summary["scenario_count"] = len(scenarios)
        summary["completed_count"] = len(results)
        summary["remaining_count"] = max(0, len(scenarios) - len(results))
        run["summary"] = summary
        run.setdefault("metadata", {})
        progress = dict(run["metadata"].get("progress") or {})
        progress["completed"] = len(results)
        progress["remaining"] = max(0, len(scenarios) - len(results))
        run["metadata"]["progress"] = progress
        self.repository.save_run(run)

    def _run_status_from_summary(self, summary: dict[str, Any]) -> str:
        if summary.get("error_count", 0) > 0:
            if summary.get("executed_count", 0) or summary.get("skipped_count", 0):
                return "completed_with_errors"
            return "failed"
        return "completed"
