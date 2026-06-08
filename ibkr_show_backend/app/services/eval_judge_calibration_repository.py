from __future__ import annotations

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings


JUDGE_CALIBRATION_RUN_INDEX = "ibkr_agent_eval_judge_calibration_runs"
JUDGE_CALIBRATION_SIGNAL_INDEX = "ibkr_agent_eval_judge_calibration_signals"


JUDGE_CALIBRATION_RUN_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "calibration_run_id": {"type": "keyword"},
            "source_type": {"type": "keyword"},
            "source_id": {"type": "keyword"},
            "status": {"type": "keyword"},
            "created_at": {"type": "date"},
            "summary": {"type": "object", "enabled": True},
            "signals": {"type": "object", "enabled": True},
            "suggestions": {"type": "object", "enabled": True},
            "config": {"type": "object", "enabled": True},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


JUDGE_CALIBRATION_SIGNAL_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "signal_id": {"type": "keyword"},
            "calibration_run_id": {"type": "keyword"},
            "signal_type": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "failure_id": {"type": "keyword"},
            "simulation_result_id": {"type": "keyword"},
            "scenario_id": {"type": "keyword"},
            "severity": {"type": "keyword"},
            "priority": {"type": "integer"},
            "rule_check_status": {"type": "keyword"},
            "judge_status": {"type": "keyword"},
            "affected_dimensions": {"type": "keyword"},
            "should_create_calibration_case": {"type": "boolean"},
            "duplicate_key": {"type": "keyword"},
            "created_at": {"type": "date"},
            "failed_checks": {"type": "object", "enabled": True},
            "judge_result": {"type": "object", "enabled": True},
            "evidence": {"type": "object", "enabled": True},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


class JudgeCalibrationRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def save_run(self, run: dict) -> dict:
        self.es_client.create_index_if_missing(JUDGE_CALIBRATION_RUN_INDEX, JUDGE_CALIBRATION_RUN_INDEX_BODY)
        self.es_client.index_document(index=JUDGE_CALIBRATION_RUN_INDEX, id=run["calibration_run_id"], document=run)
        return run

    def get_run(self, calibration_run_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=JUDGE_CALIBRATION_RUN_INDEX, id=calibration_run_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_runs(
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
            "sort": [{"created_at": {"order": "desc"}}],
            "size": max(1, min(int(limit), 10000)),
            "_source": True,
        }
        try:
            response = self.es_client.search(index=JUDGE_CALIBRATION_RUN_INDEX, body=body)
        except ESIndexNotFoundError:
            return []
        items = [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]
        if agent_name:
            items = [
                item for item in items
                if agent_name in ((item.get("summary") or {}).get("by_agent") or {})
            ]
        return items

    def save_signal(self, signal: dict) -> dict:
        self.es_client.create_index_if_missing(JUDGE_CALIBRATION_SIGNAL_INDEX, JUDGE_CALIBRATION_SIGNAL_INDEX_BODY)
        self.es_client.index_document(index=JUDGE_CALIBRATION_SIGNAL_INDEX, id=signal["signal_id"], document=signal)
        return signal

    def list_signals(
        self,
        *,
        calibration_run_id: str | None = None,
        agent_name: str | None = None,
        signal_type: str | None = None,
        min_priority: int | None = None,
        should_create_calibration_case: bool | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        filters: list[dict] = []
        if calibration_run_id:
            filters.append({"term": {"calibration_run_id": calibration_run_id}})
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        if signal_type:
            filters.append({"term": {"signal_type": signal_type}})
        if should_create_calibration_case is not None:
            filters.append({"term": {"should_create_calibration_case": should_create_calibration_case}})
        body = {
            "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
            "sort": [{"priority": {"order": "desc"}}, {"created_at": {"order": "desc"}}],
            "size": max(1, min(int(limit), 10000)),
            "_source": True,
        }
        try:
            response = self.es_client.search(index=JUDGE_CALIBRATION_SIGNAL_INDEX, body=body)
        except ESIndexNotFoundError:
            return []
        items = [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]
        if min_priority is not None:
            items = [item for item in items if int(item.get("priority") or 0) >= int(min_priority)]
        return items

    def get_signal(self, signal_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=JUDGE_CALIBRATION_SIGNAL_INDEX, id=signal_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None


class InMemoryJudgeCalibrationRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}
        self.signals: dict[str, dict] = {}

    def save_run(self, run: dict) -> dict:
        self.runs[run["calibration_run_id"]] = dict(run)
        return run

    def get_run(self, calibration_run_id: str) -> dict | None:
        run = self.runs.get(calibration_run_id)
        return dict(run) if run else None

    def list_runs(
        self,
        *,
        agent_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        items = list(self.runs.values())
        if status:
            items = [item for item in items if item.get("status") == status]
        if agent_name:
            items = [
                item for item in items
                if agent_name in ((item.get("summary") or {}).get("by_agent") or {})
            ]
        items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return [dict(item) for item in items[:limit]]

    def save_signal(self, signal: dict) -> dict:
        self.signals[signal["signal_id"]] = dict(signal)
        return signal

    def list_signals(
        self,
        *,
        calibration_run_id: str | None = None,
        agent_name: str | None = None,
        signal_type: str | None = None,
        min_priority: int | None = None,
        should_create_calibration_case: bool | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        items = list(self.signals.values())
        if calibration_run_id:
            items = [item for item in items if item.get("calibration_run_id") == calibration_run_id]
        if agent_name:
            items = [item for item in items if item.get("agent_name") == agent_name]
        if signal_type:
            items = [item for item in items if item.get("signal_type") == signal_type]
        if min_priority is not None:
            items = [item for item in items if int(item.get("priority") or 0) >= int(min_priority)]
        if should_create_calibration_case is not None:
            items = [item for item in items if item.get("should_create_calibration_case") is should_create_calibration_case]
        items.sort(key=lambda item: (int(item.get("priority") or 0), item.get("created_at") or ""), reverse=True)
        return [dict(item) for item in items[:limit]]

    def get_signal(self, signal_id: str) -> dict | None:
        signal = self.signals.get(signal_id)
        return dict(signal) if signal else None
