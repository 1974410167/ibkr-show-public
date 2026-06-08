from __future__ import annotations

from app.services.eval_judge_calibration_repository import InMemoryJudgeCalibrationRepository


def test_in_memory_judge_calibration_repository_filters_runs_and_signals() -> None:
    repo = InMemoryJudgeCalibrationRepository()
    repo.save_run({
        "calibration_run_id": "run-1",
        "status": "completed",
        "created_at": "2026-01-01T00:00:00+00:00",
        "summary": {"by_agent": {"trade_decision": 1}},
    })
    repo.save_signal({
        "signal_id": "signal-1",
        "calibration_run_id": "run-1",
        "agent_name": "trade_decision",
        "signal_type": "judge_too_lenient",
        "priority": 90,
        "should_create_calibration_case": True,
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    repo.save_signal({
        "signal_id": "signal-2",
        "calibration_run_id": "run-1",
        "agent_name": "trade_review",
        "signal_type": "judge_low_confidence",
        "priority": 60,
        "should_create_calibration_case": False,
        "created_at": "2026-01-01T00:00:01+00:00",
    })

    assert repo.get_run("run-1")["calibration_run_id"] == "run-1"
    assert repo.list_runs(agent_name="trade_decision")[0]["calibration_run_id"] == "run-1"
    assert repo.get_signal("signal-1")["signal_type"] == "judge_too_lenient"
    assert len(repo.list_signals(calibration_run_id="run-1")) == 2
    assert repo.list_signals(agent_name="trade_decision")[0]["signal_id"] == "signal-1"
    assert repo.list_signals(signal_type="judge_low_confidence")[0]["signal_id"] == "signal-2"
    assert repo.list_signals(min_priority=80)[0]["signal_id"] == "signal-1"
    assert repo.list_signals(should_create_calibration_case=True)[0]["signal_id"] == "signal-1"
