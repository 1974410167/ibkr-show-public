from __future__ import annotations

from app.services.eval_failure_mining_repository import InMemorySyntheticFailureMiningRepository


def test_in_memory_failure_mining_repository_filters_runs_and_items() -> None:
    repo = InMemorySyntheticFailureMiningRepository()
    run = {
        "failure_mining_run_id": "fm-1",
        "simulation_run_id": "sim-1",
        "agent_names": ["trade_decision"],
        "status": "completed",
        "started_at": "2026-01-01T00:00:00+00:00",
        "summary": {"by_agent": {"trade_decision": 1}},
    }
    item = {
        "failure_id": "f-1",
        "failure_mining_run_id": "fm-1",
        "simulation_run_id": "sim-1",
        "agent_name": "trade_decision",
        "severity": "high",
        "failure_type": "missing_risk_control",
        "should_convert_to_eval_case": True,
        "conversion_priority": 90,
        "created_at": "2026-01-01T00:00:01+00:00",
    }

    repo.save_failure_mining_run(run)
    repo.save_failure_item(item)

    assert repo.get_failure_mining_run("fm-1")["simulation_run_id"] == "sim-1"
    assert repo.list_failure_mining_runs(simulation_run_id="sim-1")[0]["failure_mining_run_id"] == "fm-1"
    assert repo.list_failure_mining_runs(agent_name="trade_decision")[0]["failure_mining_run_id"] == "fm-1"
    assert repo.get_failure_item("f-1")["failure_type"] == "missing_risk_control"
    assert repo.list_failure_items(agent_name="trade_decision", min_severity="medium")[0]["failure_id"] == "f-1"
    assert repo.list_failure_items(failure_type="missing_risk_control")[0]["failure_id"] == "f-1"
    assert repo.list_failure_items(should_convert_to_eval_case=True)[0]["failure_id"] == "f-1"
    assert repo.get_failure_mining_run("missing") is None
    assert repo.get_failure_item("missing") is None
