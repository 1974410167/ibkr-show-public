from __future__ import annotations

from datetime import date, timedelta
import time
from typing import Any, Protocol


class SimulationAgentExecutor(Protocol):
    def execute(self, scenario: dict) -> dict[str, Any]:
        ...


def _scenario_symbol(scenario: dict, default: str = "AMD.US") -> str:
    context = scenario.get("mock_context") or {}
    metadata = scenario.get("metadata") or {}
    return str(metadata.get("symbol") or context.get("symbol") or default)


def _placeholder_output(scenario: dict) -> dict[str, Any]:
    agent_name = scenario.get("agent_name")
    scenario_type = (scenario.get("metadata") or {}).get("scenario_type")
    if agent_name == "trade_decision":
        return {
            "decision_summary": f"Dry-run placeholder for {scenario['scenario_id']}",
            "action": "wait",
            "confidence": "low",
            "key_reasons": ["dry_run", scenario_type],
            "major_risks": list(scenario.get("failure_traps") or [])[:3],
            "data_limitations": ["synthetic dry_run placeholder; no real agent executed"],
        }
    if agent_name == "daily_position_review":
        return {
            "summary": f"Dry-run placeholder for {scenario['scenario_id']}",
            "account_conclusion": "not_evaluated",
            "attribution_summary": "dry_run only",
            "data_limitations": ["synthetic dry_run placeholder; no real agent executed"],
        }
    if agent_name == "trade_review":
        return {
            "summary": f"Dry-run placeholder for {scenario['scenario_id']}",
            "overall_score": None,
            "rating": "not_evaluated",
            "data_limitations": ["synthetic dry_run placeholder; no real agent executed"],
        }
    return {
        "answer": f"Dry-run placeholder for {scenario['scenario_id']}",
        "data_limitations": ["synthetic dry_run placeholder; no real account copilot executed"],
    }


def _standard_payload(
    *,
    scenario: dict,
    status: str,
    output: dict | str,
    latency_ms: int,
    error_code: str | None = None,
    error_message: str | None = None,
    metadata: dict | None = None,
    source_document_id: str | None = None,
    source_run_id: str | None = None,
    source_task_id: str | None = None,
) -> dict[str, Any]:
    output_summary = {}
    if isinstance(output, dict):
        output_summary = {
            key: output.get(key)
            for key in ("decision_summary", "summary", "answer", "action", "confidence", "rating")
            if key in output
        }
    return {
        "status": status,
        "output": output,
        "output_summary": output_summary,
        "run_trace": [],
        "node_outputs": [],
        "tool_calls": [],
        "latency_ms": latency_ms,
        "error_code": error_code,
        "error_message": error_message,
        "source_run_id": source_run_id,
        "source_task_id": source_task_id,
        "source_document_id": source_document_id,
        "metadata": metadata or {},
    }


class FakeSimulationAgentExecutor:
    def execute(self, scenario: dict) -> dict[str, Any]:
        start = time.perf_counter()
        output = _placeholder_output(scenario)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return _standard_payload(
            scenario=scenario,
            status="skipped",
            output=output,
            latency_ms=latency_ms,
            metadata={
                "executor_mode": "fake",
                "dry_run": True,
                "agent_called": False,
                "scenario_type": (scenario.get("metadata") or {}).get("scenario_type"),
            },
        )


class DryRunSimulationAgentExecutor(FakeSimulationAgentExecutor):
    def execute(self, scenario: dict) -> dict[str, Any]:
        payload = super().execute(scenario)
        payload["metadata"]["executor_mode"] = "dry_run"
        return payload


class RealSimulationAgentExecutor:
    def __init__(
        self,
        *,
        trade_decision_agent: Any = None,
        daily_position_review_agent: Any = None,
        daily_position_review_service: Any = None,
        trade_review_agent: Any = None,
        account_copilot_executor: SimulationAgentExecutor | None = None,
        allow_live_account_copilot: bool = False,
    ) -> None:
        self.trade_decision_agent = trade_decision_agent
        self.daily_position_review_agent = daily_position_review_agent
        self.daily_position_review_service = daily_position_review_service
        self.trade_review_agent = trade_review_agent
        self.account_copilot_executor = account_copilot_executor
        self.allow_live_account_copilot = allow_live_account_copilot

    def execute(self, scenario: dict) -> dict[str, Any]:
        agent_name = scenario.get("agent_name")
        if agent_name == "trade_decision":
            return self._execute_trade_decision(scenario)
        if agent_name == "daily_position_review":
            return self._execute_daily_position_review(scenario)
        if agent_name == "trade_review":
            return self._execute_trade_review(scenario)
        if agent_name == "account_copilot":
            return self._execute_account_copilot(scenario)
        return self._skipped(scenario, "UNSUPPORTED_AGENT", f"Unsupported agent: {agent_name}")

    def _execute_trade_decision(self, scenario: dict) -> dict[str, Any]:
        if self.trade_decision_agent is None:
            return self._skipped(scenario, "EXECUTOR_NOT_CONFIGURED", "trade_decision real executor not configured")
        metadata = scenario.get("metadata") or {}
        decision_type = metadata.get("decision_type") or (scenario.get("mock_context") or {}).get("decision_type") or "entry"
        symbol = _scenario_symbol(scenario)
        question = scenario.get("user_question")
        start = time.perf_counter()
        try:
            if decision_type == "holding":
                document = self.trade_decision_agent.analyze_holding(symbol=symbol, question=question)
            else:
                document = self.trade_decision_agent.analyze_entry(symbol=symbol, question=question)
        except Exception as exc:
            return self._error(scenario, exc, start)
        return self._document_payload(scenario, document, start)

    def _execute_daily_position_review(self, scenario: dict) -> dict[str, Any]:
        if self.daily_position_review_agent is None:
            return self._skipped(scenario, "EXECUTOR_NOT_CONFIGURED", "daily_position_review real executor not configured")
        report_date, resolution = self._resolve_daily_report_date(scenario)
        if not report_date:
            return self._skipped(scenario, "MISSING_REPORT_DATE", "daily_position_review scenario missing report_date")
        start = time.perf_counter()
        try:
            document = self.daily_position_review_agent.generate_review(report_date=report_date)
        except Exception as exc:
            return self._error(scenario, exc, start)
        return self._document_payload(scenario, document, start, metadata=resolution)

    def _execute_trade_review(self, scenario: dict) -> dict[str, Any]:
        if self.trade_review_agent is None:
            return self._skipped(scenario, "EXECUTOR_NOT_CONFIGURED", "trade_review real executor not configured")
        context = scenario.get("mock_context") or {}
        metadata = scenario.get("metadata") or {}
        review_type = metadata.get("review_type") or context.get("review_type") or "symbol_level_review"
        start = time.perf_counter()
        try:
            if review_type == "single_trade_review":
                trade_id = metadata.get("trade_id") or context.get("trade_id")
                if not trade_id:
                    return self._skipped(scenario, "MISSING_TRADE_ID", "single trade review scenario missing trade_id")
                document = self.trade_review_agent.generate_single_trade_review(trade_id=str(trade_id))
            else:
                symbol = _scenario_symbol(scenario)
                start_date, end_date, resolution = self._resolve_trade_review_window(scenario)
                if not start_date or not end_date:
                    return self._skipped(scenario, "MISSING_REVIEW_WINDOW", "symbol review scenario missing start_date/end_date")
                document = self.trade_review_agent.generate_symbol_review(symbol=symbol, start_date=start_date, end_date=end_date)
        except Exception as exc:
            return self._error(scenario, exc, start)
        if review_type == "single_trade_review":
            return self._document_payload(scenario, document, start, metadata={"review_type": review_type})
        return self._document_payload(scenario, document, start, metadata={"review_type": review_type, **resolution})

    def _execute_account_copilot(self, scenario: dict) -> dict[str, Any]:
        if not self.allow_live_account_copilot:
            return self._skipped(
                scenario,
                "ACCOUNT_COPILOT_LIVE_DISABLED",
                "account_copilot real executor requires allow_live_account_copilot=True",
            )
        if self.account_copilot_executor is None:
            return self._skipped(scenario, "EXECUTOR_NOT_CONFIGURED", "account_copilot real executor not configured")
        return self.account_copilot_executor.execute(scenario)

    def _resolve_daily_report_date(self, scenario: dict) -> tuple[str | None, dict[str, Any]]:
        context = scenario.get("mock_context") or {}
        metadata = scenario.get("metadata") or {}
        explicit_date = metadata.get("report_date") or context.get("report_date")
        strategy = metadata.get("report_date_strategy") or context.get("report_date_strategy")
        resolution = {"report_date_strategy": strategy}
        if explicit_date:
            report_date = str(explicit_date)
            return report_date, {
                **resolution,
                "resolved_report_date": report_date,
                "report_date_resolution_source": "explicit",
            }
        if strategy == "latest_available":
            report_dates: list[str] = []
            service_error: str | None = None
            if self.daily_position_review_service is not None:
                try:
                    report_dates = list(self.daily_position_review_service.list_report_dates(limit=1) or [])
                except Exception as exc:
                    service_error = str(exc)
            if report_dates:
                report_date = str(report_dates[0])
                return report_date, {
                    **resolution,
                    "resolved_report_date": report_date,
                    "report_date_resolution_source": "latest_available",
                }
            fallback_date = (date.today() - timedelta(days=1)).isoformat()
            return fallback_date, {
                **resolution,
                "resolved_report_date": fallback_date,
                "report_date_resolution_source": "fallback_previous_day",
                "report_date_resolution_error": service_error,
            }
        return None, resolution

    def _resolve_trade_review_window(self, scenario: dict) -> tuple[str | None, str | None, dict[str, Any]]:
        context = scenario.get("mock_context") or {}
        metadata = scenario.get("metadata") or {}
        start_date = metadata.get("start_date") or context.get("start_date")
        end_date = metadata.get("end_date") or context.get("end_date")
        start_strategy = metadata.get("start_date_strategy") or context.get("start_date_strategy")
        end_strategy = metadata.get("end_date_strategy") or context.get("end_date_strategy")
        source_parts: list[str] = []
        if not end_date and end_strategy == "latest_available_or_today":
            end_date = date.today().isoformat()
            source_parts.append("end_date:today")
        elif end_date:
            source_parts.append("end_date:explicit")
        if not start_date and start_strategy == "recent_60d" and end_date:
            start_date = (date.fromisoformat(str(end_date)) - timedelta(days=60)).isoformat()
            source_parts.append("start_date:recent_60d")
        elif start_date:
            source_parts.append("start_date:explicit")
        return (
            str(start_date) if start_date else None,
            str(end_date) if end_date else None,
            {
                "start_date_strategy": start_strategy,
                "end_date_strategy": end_strategy,
                "resolved_start_date": str(start_date) if start_date else None,
                "resolved_end_date": str(end_date) if end_date else None,
                "date_window_resolution_source": ",".join(source_parts) or None,
            },
        )

    def _document_payload(self, scenario: dict, document: dict, start: float, *, metadata: dict | None = None) -> dict[str, Any]:
        latency_ms = int((time.perf_counter() - start) * 1000)
        output = dict(document or {})
        return {
            **_standard_payload(
                scenario=scenario,
                status="passed",
                output=output,
                latency_ms=latency_ms,
                source_document_id=output.get("id"),
                source_run_id=output.get("run_id"),
                source_task_id=output.get("task_id"),
                metadata={"executor_mode": "real", "dry_run": False, "agent_called": True, **(metadata or {})},
            ),
            "run_trace": output.get("run_trace") or [],
            "node_outputs": output.get("graph_node_traces") or output.get("node_outputs") or [],
            "tool_calls": output.get("tool_calls") or [],
        }

    def _skipped(self, scenario: dict, error_code: str, message: str) -> dict[str, Any]:
        return _standard_payload(
            scenario=scenario,
            status="skipped",
            output={},
            latency_ms=0,
            error_code=error_code,
            error_message=message,
            metadata={"executor_mode": "real", "dry_run": False, "agent_called": False},
        )

    def _error(self, scenario: dict, exc: Exception, start: float) -> dict[str, Any]:
        return _standard_payload(
            scenario=scenario,
            status="error",
            output={},
            latency_ms=int((time.perf_counter() - start) * 1000),
            error_code=getattr(exc, "error_code", "EXECUTOR_ERROR"),
            error_message=getattr(exc, "message", str(exc)),
            metadata={"executor_mode": "real", "dry_run": False, "agent_called": True},
        )
