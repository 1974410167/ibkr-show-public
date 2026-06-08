from __future__ import annotations

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings


BASELINE_HEALTH_REPORT_INDEX = "ibkr_agent_eval_baseline_health_reports"


BASELINE_HEALTH_REPORT_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "report_id": {"type": "keyword"},
            "name": {"type": "keyword"},
            "simulation_run_id": {"type": "keyword"},
            "failure_mining_run_id": {"type": "keyword"},
            "generated_at": {"type": "date"},
            "status": {"type": "keyword"},
            "summary": {"type": "object", "enabled": True},
            "by_agent": {"type": "object", "enabled": True},
            "by_failure_type": {"type": "object", "enabled": True},
            "by_dimension": {"type": "object", "enabled": True},
            "recommendations": {"type": "object", "enabled": True},
            "architecture_signals": {"type": "object", "enabled": True},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


class BaselineHealthReportRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def save_report(self, report: dict) -> dict:
        self.es_client.create_index_if_missing(BASELINE_HEALTH_REPORT_INDEX, BASELINE_HEALTH_REPORT_INDEX_BODY)
        self.es_client.index_document(index=BASELINE_HEALTH_REPORT_INDEX, id=report["report_id"], document=report)
        return report

    def get_report(self, report_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=BASELINE_HEALTH_REPORT_INDEX, id=report_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_reports(
        self,
        *,
        agent_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        filters: list[dict] = []
        if status:
            filters.append({"term": {"status": status}})
        body = {
            "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
            "sort": [{"generated_at": {"order": "desc"}}],
            "size": max(1, min(int(limit), 10000)),
            "_source": True,
        }
        try:
            response = self.es_client.search(index=BASELINE_HEALTH_REPORT_INDEX, body=body)
        except ESIndexNotFoundError:
            return []
        items = [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]
        if agent_name:
            items = [
                item for item in items
                if any(row.get("agent_name") == agent_name for row in (item.get("by_agent") or []))
            ]
        return items


class InMemoryBaselineHealthReportRepository:
    def __init__(self) -> None:
        self.reports: dict[str, dict] = {}

    def save_report(self, report: dict) -> dict:
        self.reports[report["report_id"]] = dict(report)
        return report

    def get_report(self, report_id: str) -> dict | None:
        report = self.reports.get(report_id)
        return dict(report) if report else None

    def list_reports(
        self,
        *,
        agent_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        items = list(self.reports.values())
        if status:
            items = [item for item in items if item.get("status") == status]
        if agent_name:
            items = [
                item for item in items
                if any(row.get("agent_name") == agent_name for row in (item.get("by_agent") or []))
            ]
        items.sort(key=lambda item: item.get("generated_at") or "", reverse=True)
        return [dict(item) for item in items[:limit]]
