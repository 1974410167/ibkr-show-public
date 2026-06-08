from __future__ import annotations

from typing import Any

from app.agents.eval_failure_to_case import (
    FailureCaseConversionResult,
    FailureCaseDraft,
    build_case_duplicate_key,
    build_eval_case_payload_from_failure,
    new_failure_case_draft_id,
    score_failure_case_quality,
    utc_now_iso,
)
from app.agents.eval_harness import EvalCase
from app.agents.eval_simulation_scenarios import get_synthetic_scenario


class FailureToEvalCaseService:
    def __init__(
        self,
        *,
        failure_repository: Any,
        simulation_repository: Any,
        case_repository: Any,
    ) -> None:
        self.failure_repository = failure_repository
        self.simulation_repository = simulation_repository
        self.case_repository = case_repository

    def preview_case_from_failure(self, failure_id: str, *, enabled: bool = False) -> dict[str, Any]:
        failure, scenario, simulation_result = self._load_sources(failure_id)
        quality = score_failure_case_quality(failure, scenario, simulation_result)
        payload = build_eval_case_payload_from_failure(
            failure,
            scenario,
            simulation_result,
            enabled=enabled,
        )
        duplicate = self.find_existing_case_for_failure(failure, scenario)
        warnings = list(quality["warnings"])
        if duplicate:
            warnings.append(f"duplicate case exists: {duplicate.get('case_id')}")
        draft = FailureCaseDraft(
            draft_id=new_failure_case_draft_id(),
            failure_id=failure_id,
            agent_name=failure.get("agent_name") or scenario.get("agent_name"),
            case_payload=payload,
            conversion_reason=failure.get("recommendation") or "High-value synthetic failure",
            conversion_priority=int(failure.get("conversion_priority") or 0),
            quality_score=float(quality["quality_score"]),
            quality_warnings=warnings,
            metadata={
                "eligible": quality["eligible"],
                "duplicate_case_id": duplicate.get("case_id") if duplicate else None,
            },
        ).to_dict()
        return {"draft": draft, "quality": quality, "duplicate": duplicate}

    def convert_failure_to_case(
        self,
        failure_id: str,
        *,
        enabled: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        preview = self.preview_case_from_failure(failure_id, enabled=enabled)
        draft = preview["draft"]
        quality = preview["quality"]
        duplicate = preview["duplicate"]
        if duplicate and not force:
            return FailureCaseConversionResult(
                failure_id=failure_id,
                draft_id=draft["draft_id"],
                case_id=duplicate.get("case_id"),
                status="duplicate",
                reason="Matching EvalCase already exists",
                case_payload=draft["case_payload"],
                metadata={"existing_case_id": duplicate.get("case_id")},
            ).to_dict()
        if not quality["eligible"] and not force:
            return FailureCaseConversionResult(
                failure_id=failure_id,
                draft_id=draft["draft_id"],
                case_id=None,
                status="skipped",
                reason="Failure quality score is below conversion threshold",
                case_payload=draft["case_payload"],
                metadata={"quality": quality},
            ).to_dict()

        payload = dict(draft["case_payload"])
        if duplicate and force:
            payload["case_id"] = f"{payload['case_id']}_forced"
        case = EvalCase.from_dict(payload)
        saved = self.case_repository.save_case(case.to_dict())
        self._mark_failure_converted(failure_id, saved["case_id"], status="converted")
        return FailureCaseConversionResult(
            failure_id=failure_id,
            draft_id=draft["draft_id"],
            case_id=saved["case_id"],
            status="saved",
            reason="EvalCase saved as disabled draft" if not enabled else "EvalCase saved",
            case_payload=saved,
            metadata={"quality": quality, "forced": force},
        ).to_dict()

    def batch_convert_failures(
        self,
        *,
        failure_mining_run_id: str | None = None,
        failure_ids: list[str] | None = None,
        min_priority: int = 80,
        max_cases: int = 20,
        enabled: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        failures = self._select_failures(
            failure_mining_run_id=failure_mining_run_id,
            failure_ids=failure_ids,
            min_priority=min_priority,
            max_cases=max_cases,
        )
        results: list[dict[str, Any]] = []
        for failure in failures:
            try:
                results.append(self.convert_failure_to_case(
                    failure["failure_id"],
                    enabled=enabled,
                    force=force,
                ))
            except Exception as exc:
                results.append(FailureCaseConversionResult(
                    failure_id=failure.get("failure_id", ""),
                    draft_id=None,
                    case_id=None,
                    status="error",
                    reason=str(exc),
                ).to_dict())
        return {
            "converted_count": sum(1 for item in results if item["status"] == "saved"),
            "skipped_count": sum(1 for item in results if item["status"] == "skipped"),
            "duplicate_count": sum(1 for item in results if item["status"] == "duplicate"),
            "error_count": sum(1 for item in results if item["status"] == "error"),
            "results": results,
        }

    def find_existing_case_for_failure(self, failure: dict, scenario: dict) -> dict | None:
        failure_id = failure.get("failure_id")
        duplicate_key = build_case_duplicate_key(failure, scenario)
        agent_name = failure.get("agent_name") or scenario.get("agent_name")
        failure_type = failure.get("failure_type")
        category = scenario.get("category") or failure_type
        candidates = self.case_repository.list_cases(
            agent_name=agent_name,
            source="synthetic_failure",
            include_archived=True,
            limit=10000,
        )
        for case in candidates:
            metadata = case.get("metadata") or {}
            tags = set(case.get("tags") or [])
            if metadata.get("failure_id") == failure_id:
                return case
            if metadata.get("duplicate_key") == duplicate_key:
                return case
            if (
                "failure_mined" in tags
                and case.get("agent_name") == agent_name
                and metadata.get("failure_type") == failure_type
                and case.get("category") == category
            ):
                return case
        return None

    def _load_sources(self, failure_id: str) -> tuple[dict, dict, dict]:
        failure = self.failure_repository.get_failure_item(failure_id)
        if failure is None:
            raise ValueError("Failure item not found")
        scenario = get_synthetic_scenario(failure.get("scenario_id") or "")
        if scenario is None:
            raise ValueError("Synthetic scenario not found")
        simulation_result = self.simulation_repository.get_result(failure.get("simulation_result_id") or "")
        if simulation_result is None:
            raise ValueError("Simulation result not found")
        return failure, scenario, simulation_result

    def _mark_failure_converted(self, failure_id: str, case_id: str, *, status: str) -> None:
        failure = self.failure_repository.get_failure_item(failure_id)
        if not failure:
            return
        metadata = dict(failure.get("metadata") or {})
        metadata.update({
            "converted_case_id": case_id,
            "conversion_status": status,
            "converted_at": utc_now_iso(),
        })
        failure["metadata"] = metadata
        failure["converted_case_id"] = case_id
        self.failure_repository.save_failure_item(failure)

    def _select_failures(
        self,
        *,
        failure_mining_run_id: str | None,
        failure_ids: list[str] | None,
        min_priority: int,
        max_cases: int,
    ) -> list[dict]:
        if failure_ids:
            failures = []
            for failure_id in failure_ids:
                failure = self.failure_repository.get_failure_item(failure_id)
                if failure:
                    failures.append(failure)
        else:
            failures = self.failure_repository.list_failure_items(
                failure_mining_run_id=failure_mining_run_id,
                should_convert_to_eval_case=True,
                limit=10000,
            )
        failures = [
            failure for failure in failures
            if failure.get("should_convert_to_eval_case") and int(failure.get("conversion_priority") or 0) >= min_priority
        ]
        failures.sort(key=lambda item: int(item.get("conversion_priority") or 0), reverse=True)
        return failures[: max(1, min(int(max_cases), 100))]
