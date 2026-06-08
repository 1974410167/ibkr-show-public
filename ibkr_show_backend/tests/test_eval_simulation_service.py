from __future__ import annotations

from datetime import date
import threading
import time

import pytest

from app.agents.eval_simulation_scenarios import filter_synthetic_scenarios
from app.api import deps
from app.services.eval_simulation_executors import FakeSimulationAgentExecutor, RealSimulationAgentExecutor
from app.services.eval_simulation_repository import InMemorySyntheticSimulationRepository
from app.services.eval_simulation_service import SyntheticSimulationService


class CountingExecutor(FakeSimulationAgentExecutor):
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, scenario: dict) -> dict:
        self.calls += 1
        payload = super().execute(scenario)
        payload["metadata"]["counting_executor"] = True
        return payload


class FakeTradeDecisionAgent:
    def __init__(self) -> None:
        self.entry_calls = 0

    def analyze_entry(self, **kwargs) -> dict:
        self.entry_calls += 1
        return {"id": "doc-1", "decision_summary": "ok", "action": "wait", "confidence": "low"}

    def analyze_holding(self, **kwargs) -> dict:
        return self.analyze_entry(**kwargs)


class FakeDailyPositionReviewAgent:
    def __init__(self) -> None:
        self.report_dates: list[str] = []

    def generate_review(self, *, report_date: str) -> dict:
        self.report_dates.append(report_date)
        return {"id": "daily-doc-1", "summary": "ok", "report_date": report_date}


class FakeDailyPositionReviewService:
    def __init__(self, dates: list[str]) -> None:
        self.dates = dates
        self.calls = 0

    def list_report_dates(self, *, limit: int = 60) -> list[str]:
        self.calls += 1
        return self.dates[:limit]


class FakeTradeReviewAgent:
    def __init__(self) -> None:
        self.symbol_calls: list[dict] = []

    def generate_symbol_review(self, **kwargs) -> dict:
        self.symbol_calls.append(kwargs)
        return {"id": "trade-review-doc-1", "summary": "ok", **kwargs}


class BlockingExecutor(FakeSimulationAgentExecutor):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def execute(self, scenario: dict) -> dict:
        self.started.set()
        self.release.wait(timeout=5)
        return super().execute(scenario)


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached before timeout")


def test_dry_run_creates_run_and_results_without_calling_real_executor() -> None:
    repo = InMemorySyntheticSimulationRepository()
    fake = CountingExecutor()
    real = CountingExecutor()
    service = SyntheticSimulationService(repo, fake_executor=fake, real_executor=real)

    result = service.run_scenarios(agent_name="trade_decision", tag="chase_high", limit=2, dry_run=True)

    run = result["simulation_run"]
    results = result["results"]
    assert run["status"] == "completed"
    assert run["summary"]["scenario_count"] == 2
    assert run["summary"]["skipped_count"] == 2
    assert run["summary"]["dry_run"] is True
    assert len(results) == 2
    assert all(item["metadata"]["dry_run"] is True for item in results)
    assert all(item["latency_ms"] >= 0 for item in results)
    assert fake.calls == 0
    assert real.calls == 0
    assert repo.get_run(run["simulation_run_id"]) is not None
    assert len(repo.list_results(run["simulation_run_id"])) == 2


def test_auto_mode_non_dry_run_uses_fake_executor_without_calling_real() -> None:
    repo = InMemorySyntheticSimulationRepository()
    fake = CountingExecutor()
    real = CountingExecutor()
    service = SyntheticSimulationService(repo, fake_executor=fake, real_executor=real)

    result = service.run_scenarios(agent_name="trade_decision", tag="chase_high", limit=1, dry_run=False, executor_mode="auto")

    assert result["results"][0]["metadata"]["executor_mode"] == "fake"
    assert fake.calls == 1
    assert real.calls == 0


def test_real_mode_non_dry_run_calls_injected_real_agent() -> None:
    repo = InMemorySyntheticSimulationRepository()
    agent = FakeTradeDecisionAgent()
    real = RealSimulationAgentExecutor(trade_decision_agent=agent)
    service = SyntheticSimulationService(repo, real_executor=real)

    result = service.run_scenarios(agent_name="trade_decision", tag="chase_high", limit=1, dry_run=False, executor_mode="real")

    assert agent.entry_calls == 1
    assert result["results"][0]["status"] == "passed"
    assert result["results"][0]["metadata"]["executor_mode"] == "real"
    assert result["results"][0]["metadata"]["agent_called"] is True


def test_async_simulation_returns_running_run_and_records_progress() -> None:
    repo = InMemorySyntheticSimulationRepository()
    executor = BlockingExecutor()
    service = SyntheticSimulationService(repo, real_executor=executor)

    created = service.start_scenarios_async(
        agent_name="trade_decision",
        tag="chase_high",
        limit=1,
        dry_run=False,
        executor_mode="real",
        name="async test",
    )

    run_id = created["simulation_run"]["simulation_run_id"]
    assert created["simulation_run"]["status"] == "running"
    assert created["results"] == []
    assert created["simulation_run"]["config"]["async_run"] is True
    assert executor.started.wait(timeout=2)

    run = repo.get_run(run_id)
    assert run["metadata"]["current_scenario_id"]
    assert run["metadata"]["current_scenario_index"] == 1
    assert run["metadata"]["progress"]["total"] == 1
    assert repo.list_results(run_id) == []

    executor.release.set()
    _wait_until(lambda: repo.get_run(run_id)["status"] == "completed")
    final_run = repo.get_run(run_id)
    assert final_run["summary"]["completed_count"] == 1
    assert final_run["metadata"]["current_scenario_id"] is None
    assert len(repo.list_results(run_id)) == 1


def test_get_eval_simulation_service_injects_real_executor(monkeypatch) -> None:
    repo = InMemorySyntheticSimulationRepository()
    monkeypatch.setattr(deps, "get_eval_simulation_repository", lambda: repo)
    monkeypatch.setattr(deps, "get_trade_decision_agent", lambda: "trade-decision-agent")
    monkeypatch.setattr(deps, "get_daily_position_review_agent", lambda: "daily-position-review-agent")
    monkeypatch.setattr(deps, "get_daily_position_review_service", lambda: "daily-position-review-service")
    monkeypatch.setattr(deps, "get_trade_review_agent", lambda: "trade-review-agent")

    service = deps.get_eval_simulation_service()

    assert isinstance(service.real_executor, RealSimulationAgentExecutor)
    assert service.real_executor.trade_decision_agent == "trade-decision-agent"
    assert service.real_executor.daily_position_review_agent == "daily-position-review-agent"
    assert service.real_executor.daily_position_review_service == "daily-position-review-service"
    assert service.real_executor.trade_review_agent == "trade-review-agent"
    assert service.real_executor.allow_live_account_copilot is False


def test_fake_executor_mode_outputs_are_deterministic() -> None:
    repo = InMemorySyntheticSimulationRepository()
    fake = CountingExecutor()
    service = SyntheticSimulationService(repo, fake_executor=fake)

    result = service.run_scenarios(agent_name="account_copilot", limit=1, dry_run=False, executor_mode="fake")
    item = result["results"][0]

    assert fake.calls == 1
    assert item["status"] == "skipped"
    assert item["metadata"]["executor_mode"] == "fake"
    assert item["metadata"]["counting_executor"] is True
    assert "Dry-run placeholder" in item["output"]["answer"]


def test_filters_scenario_ids_agent_tag_and_limit() -> None:
    scenario = filter_synthetic_scenarios(agent_name="trade_decision", tag="chase_high", limit=1)[0]
    service = SyntheticSimulationService(InMemorySyntheticSimulationRepository())

    result = service.run_scenarios(
        scenario_ids=[scenario["scenario_id"]],
        agent_name="trade_decision",
        tag="chase_high",
        limit=10,
        dry_run=True,
    )

    assert result["simulation_run"]["scenario_ids"] == [scenario["scenario_id"]]
    assert result["results"][0]["scenario_id"] == scenario["scenario_id"]


def test_unknown_scenario_id_raises_clear_error() -> None:
    service = SyntheticSimulationService(InMemorySyntheticSimulationRepository())

    with pytest.raises(ValueError, match="Unknown synthetic scenario_id"):
        service.run_scenarios(scenario_ids=["missing"], dry_run=True)


def test_list_run_detail_and_result_detail() -> None:
    service = SyntheticSimulationService(InMemorySyntheticSimulationRepository())
    created = service.run_scenarios(agent_name="trade_review", limit=1, dry_run=True)
    run_id = created["simulation_run"]["simulation_run_id"]
    result_id = created["results"][0]["simulation_result_id"]

    assert service.list_runs(agent_name="trade_review")[0]["simulation_run_id"] == run_id
    detail = service.get_run_with_results(run_id)
    assert detail is not None
    assert detail["simulation_run"]["simulation_run_id"] == run_id
    assert detail["results"][0]["simulation_result_id"] == result_id
    assert service.get_result(result_id)["simulation_result_id"] == result_id


def test_account_copilot_real_run_is_skipped_by_default() -> None:
    scenario = filter_synthetic_scenarios(agent_name="account_copilot", limit=1)[0]
    executor = RealSimulationAgentExecutor()

    payload = executor.execute(scenario)

    assert payload["status"] == "skipped"
    assert payload["error_code"] == "ACCOUNT_COPILOT_LIVE_DISABLED"
    assert payload["metadata"]["agent_called"] is False


def test_daily_position_review_real_executor_resolves_latest_report_date() -> None:
    scenario = filter_synthetic_scenarios(agent_name="daily_position_review", limit=1)[0]
    agent = FakeDailyPositionReviewAgent()
    daily_service = FakeDailyPositionReviewService(["2026-06-04"])
    executor = RealSimulationAgentExecutor(
        daily_position_review_agent=agent,
        daily_position_review_service=daily_service,
    )

    payload = executor.execute(scenario)

    assert payload["status"] == "passed"
    assert payload["error_code"] is None
    assert agent.report_dates == ["2026-06-04"]
    assert daily_service.calls == 1
    assert payload["metadata"]["resolved_report_date"] == "2026-06-04"
    assert payload["metadata"]["report_date_strategy"] == "latest_available"
    assert payload["metadata"]["report_date_resolution_source"] == "latest_available"


def test_trade_review_real_executor_resolves_recent_window() -> None:
    scenario = filter_synthetic_scenarios(agent_name="trade_review", limit=1)[0]
    agent = FakeTradeReviewAgent()
    executor = RealSimulationAgentExecutor(trade_review_agent=agent)

    payload = executor.execute(scenario)

    assert payload["status"] == "passed"
    assert payload["error_code"] is None
    assert len(agent.symbol_calls) == 1
    call = agent.symbol_calls[0]
    expected_end = date.today()
    expected_start = expected_end.toordinal() - 60
    assert date.fromisoformat(call["end_date"]) == expected_end
    assert date.fromisoformat(call["start_date"]).toordinal() == expected_start
    assert payload["metadata"]["resolved_start_date"] == call["start_date"]
    assert payload["metadata"]["resolved_end_date"] == call["end_date"]
    assert payload["metadata"]["date_window_resolution_source"] == "end_date:today,start_date:recent_60d"
