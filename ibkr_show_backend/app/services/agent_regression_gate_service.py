from __future__ import annotations

import uuid
from typing import Any

from app.services.agent_change_impact_service import AgentChangeImpactService
from app.services.agent_eval_repository import RegressionGateReportRepository


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class AgentRegressionGateService:
    def __init__(
        self,
        impact_service: AgentChangeImpactService,
        eval_service: object,
        report_repository: RegressionGateReportRepository | None = None,
    ) -> None:
        self.impact_service = impact_service
        self.eval_service = eval_service
        self.report_repository = report_repository

    def run_regression_gate(
        self,
        *,
        changed_files: list[str] | None = None,
        base_ref: str | None = None,
        head_ref: str | None = None,
        dry_run: bool = False,
        run_not_recommended: bool = False,
        max_agents: int = 10,
        save_report: bool = False,
        trigger: str = "cli",
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if changed_files:
            impact = self.impact_service.analyze_changed_files(
                changed_files, base_ref=base_ref, head_ref=head_ref, include_payload=True,
            )
        elif base_ref and head_ref:
            impact = self.impact_service.analyze_git_diff(
                base_ref, head_ref, include_payload=True,
            )
        else:
            raise ValueError("provide changed_files or base_ref+head_ref")

        agents_to_run = []
        for agent in impact.get("impacted_agents", []):
            if run_not_recommended or agent.get("recommended"):
                if agent.get("regression_payload"):
                    agents_to_run.append(agent)

        if len(agents_to_run) > max_agents:
            raise ValueError(
                f"recommended_run_count {len(agents_to_run)} exceeds max_agents {max_agents}. "
                "Increase --max-agents or narrow the changed files."
            )

        runs: list[dict[str, Any]] = []
        reasons: list[str] = []
        passed_count = 0
        failed_count = 0
        error_count = 0

        if dry_run:
            for agent in agents_to_run:
                runs.append({
                    "agent_name": agent["agent_name"],
                    "recommended": agent.get("recommended", False),
                    "eval_run_id": None,
                    "gate_passed": None,
                    "gate_result": None,
                    "regression_payload": agent.get("regression_payload"),
                    "dry_run": True,
                })
        else:
            for agent in agents_to_run:
                payload = agent["regression_payload"]
                try:
                    result = self.eval_service.run_agent_regression_eval(payload)
                    gate_result = result.get("gate_result", {})
                    gate_passed = gate_result.get("passed", False)
                    eval_run_id = result.get("eval_run", {}).get("eval_run_id")
                    if gate_passed:
                        passed_count += 1
                    else:
                        failed_count += 1
                        agent_reasons = gate_result.get("reasons", [])
                        reasons.append(
                            f"{agent['agent_name']} gate failed: {'; '.join(agent_reasons)}"
                            if agent_reasons else f"{agent['agent_name']} gate failed"
                        )
                    runs.append({
                        "agent_name": agent["agent_name"],
                        "recommended": agent.get("recommended", False),
                        "eval_run_id": eval_run_id,
                        "gate_passed": gate_passed,
                        "gate_result": gate_result,
                        "regression_payload": payload,
                        "error": None,
                    })
                except Exception as exc:
                    error_count += 1
                    reasons.append(f"{agent['agent_name']} regression error: {exc}")
                    runs.append({
                        "agent_name": agent["agent_name"],
                        "recommended": agent.get("recommended", False),
                        "eval_run_id": None,
                        "gate_passed": False,
                        "gate_result": None,
                        "regression_payload": payload,
                        "error": str(exc),
                    })

        executed_count = passed_count + failed_count + error_count
        ok = failed_count == 0 and error_count == 0

        if not agents_to_run and not dry_run:
            reasons.append("no recommended regression runs")

        result: dict[str, Any] = {
            "ok": ok,
            "mode": "regression_gate",
            "base_ref": base_ref,
            "head_ref": head_ref,
            "dry_run": dry_run,
            "summary": {
                "changed_file_count": impact.get("summary", {}).get("changed_file_count", 0),
                "impacted_agent_count": impact.get("summary", {}).get("impacted_agent_count", 0),
                "recommended_run_count": len(agents_to_run),
                "executed_run_count": executed_count if not dry_run else 0,
                "passed_run_count": passed_count if not dry_run else 0,
                "failed_run_count": (failed_count + error_count) if not dry_run else 0,
            },
            "impact_analysis": impact,
            "runs": runs,
            "reasons": reasons,
        }

        if save_report and self.report_repository:
            report = self._build_report(
                result, impact, runs, reasons,
                trigger=trigger, created_by=created_by, metadata=metadata,
            )
            self.report_repository.save_report(report)
            result["report_id"] = report["report_id"]

        return result

    def _build_report(
        self,
        result: dict[str, Any],
        impact: dict[str, Any],
        runs: list[dict[str, Any]],
        reasons: list[str],
        *,
        trigger: str,
        created_by: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        now = _utc_now_iso()
        report_id = f"regression_gate_report_{uuid.uuid4().hex[:12]}"

        impacted_agents = [a["agent_name"] for a in impact.get("impacted_agents", [])]
        recommended_agents = [a["agent_name"] for a in impact.get("impacted_agents", []) if a.get("recommended")]
        executed_agents = [r["agent_name"] for r in runs]

        if result.get("dry_run"):
            status = "dry_run"
        elif result.get("ok"):
            status = "passed"
        elif any(r.get("error") for r in runs):
            status = "error"
        else:
            status = "failed"

        return {
            "report_id": report_id,
            "mode": result.get("mode", "regression_gate"),
            "trigger": trigger,
            "status": status,
            "ok": result.get("ok", False),
            "dry_run": result.get("dry_run", False),
            "base_ref": result.get("base_ref"),
            "head_ref": result.get("head_ref"),
            "changed_files": impact.get("unmatched_files", []) + [
                f for a in impact.get("impacted_agents", []) for f in a.get("matched_files", [])
            ],
            "impacted_agents": impacted_agents,
            "recommended_agents": recommended_agents,
            "executed_agents": executed_agents,
            "summary": result.get("summary", {}),
            "impact_analysis": impact,
            "runs": runs,
            "reasons": reasons,
            "created_at": now,
            "created_by": created_by,
            "git": {
                "base_ref": result.get("base_ref"),
                "head_ref": result.get("head_ref"),
            },
            "metadata": metadata or {},
        }

    def list_reports(self, **kwargs: Any) -> dict[str, Any]:
        if not self.report_repository:
            return {"items": [], "summary": {"report_count": 0, "passed_count": 0, "failed_count": 0, "dry_run_count": 0, "error_count": 0}}
        items = self.report_repository.list_reports(**kwargs)
        passed_count = sum(1 for r in items if r.get("status") == "passed")
        failed_count = sum(1 for r in items if r.get("status") == "failed")
        dry_run_count = sum(1 for r in items if r.get("status") == "dry_run")
        error_count = sum(1 for r in items if r.get("status") == "error")
        return {
            "items": items,
            "summary": {
                "report_count": len(items),
                "passed_count": passed_count,
                "failed_count": failed_count,
                "dry_run_count": dry_run_count,
                "error_count": error_count,
            },
        }

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        if not self.report_repository:
            return None
        return self.report_repository.get_report(report_id)
