from __future__ import annotations

from app.services.eval_baseline_health_repository import InMemoryBaselineHealthReportRepository


def test_in_memory_baseline_health_report_repository_filters_reports() -> None:
    repo = InMemoryBaselineHealthReportRepository()
    report = {
        "report_id": "report-1",
        "name": "Baseline",
        "status": "completed",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "by_agent": [{"agent_name": "trade_decision"}],
    }

    repo.save_report(report)

    assert repo.get_report("report-1")["name"] == "Baseline"
    assert repo.list_reports(status="completed")[0]["report_id"] == "report-1"
    assert repo.list_reports(agent_name="trade_decision")[0]["report_id"] == "report-1"
    assert repo.get_report("missing") is None
