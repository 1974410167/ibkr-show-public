from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agents.eval_cases import list_builtin_eval_cases
from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings


EVAL_CASE_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "case_id": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "source": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "metadata": {"type": "object", "enabled": True},
            "enabled": {"type": "boolean"},
            "severity": {"type": "keyword"},
            "category": {"type": "keyword"},
            "source_replay_id": {"type": "keyword"},
            "eval_scope": {"type": "keyword"},
            "node_name": {"type": "keyword"},
            "source_run_id": {"type": "keyword"},
            "source_llm_call_id": {"type": "keyword"},
            "source_node_trace_id": {"type": "keyword"},
            "prompt_key": {"type": "keyword"},
            "prompt_version": {"type": "keyword"},
            "prompt_hash": {"type": "keyword"},
            "model": {"type": "keyword"},
            "archived": {"type": "boolean"},
            "archived_at": {"type": "date"},
            "archived_reason": {"type": "keyword"},
        }
    },
}

EVAL_RUN_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "eval_run_id": {"type": "keyword"},
            "name": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "case_ids": {"type": "keyword"},
            "started_at": {"type": "date"},
            "finished_at": {"type": "date"},
            "status": {"type": "keyword"},
            "summary": {"type": "object", "enabled": True},
            "results": {"type": "object", "enabled": True},
            "config": {"type": "object", "enabled": True},
        }
    },
}

FEEDBACK_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "feedback_id": {"type": "keyword"},
            "source_type": {"type": "keyword"},
            "source_id": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "issue_type": {"type": "keyword"},
            "severity": {"type": "keyword"},
            "category": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "status": {"type": "keyword"},
            "replay_id": {"type": "keyword"},
            "run_id": {"type": "keyword"},
            "eval_run_id": {"type": "keyword"},
            "case_id": {"type": "keyword"},
            "result_case_id": {"type": "keyword"},
            "converted_case_id": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "evidence": {"type": "object", "enabled": True},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


def since_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))).isoformat()


class EvalCaseRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    @property
    def index_name(self) -> str:
        return self.settings.es_agent_eval_case_index

    def save_case(self, case: dict) -> dict:
        self._ensure_index()
        self.es_client.index_document(index=self.index_name, id=case["case_id"], document=case)
        return case

    def get_case(self, case_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=self.index_name, id=case_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_cases(
        self,
        *,
        agent_name: str | None = None,
        source: str | None = None,
        enabled: bool | None = None,
        severity: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        source_replay_id: str | None = None,
        eval_scope: str | None = None,
        node_name: str | None = None,
        source_run_id: str | None = None,
        source_llm_call_id: str | None = None,
        prompt_key: str | None = None,
        model: str | None = None,
        include_archived: bool = False,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        filters: list[dict] = []
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        if source:
            filters.append({"term": {"source": source}})
        if enabled is not None:
            if enabled:
                filters.append({
                    "bool": {
                        "should": [
                            {"term": {"enabled": True}},
                            {"bool": {"must_not": {"exists": {"field": "enabled"}}}},
                        ],
                        "minimum_should_match": 1,
                    }
                })
            else:
                filters.append({"term": {"enabled": False}})
        if not include_archived:
            filters.append({
                "bool": {
                    "should": [
                        {"term": {"archived": False}},
                        {"bool": {"must_not": {"exists": {"field": "archived"}}}},
                    ],
                    "minimum_should_match": 1,
                }
            })
        if severity:
            filters.append({"term": {"severity": severity}})
        if category:
            filters.append({"term": {"category": category}})
        if tag:
            filters.append({"term": {"tags": tag}})
        if source_replay_id:
            filters.append({"term": {"source_replay_id": source_replay_id}})
        if eval_scope:
            # 历史 EvalCase 没有 eval_scope 字段。eval_scope=agent 时必须把
            # 缺失字段的老 case 一并返回；eval_scope=node 时只返回显式
            # 标记为 node 的 case。
            if eval_scope == "agent":
                filters.append({
                    "bool": {
                        "should": [
                            {"term": {"eval_scope": "agent"}},
                            {"bool": {"must_not": {"exists": {"field": "eval_scope"}}}},
                        ],
                        "minimum_should_match": 1,
                    }
                })
            else:
                filters.append({"term": {"eval_scope": eval_scope}})
        if node_name:
            filters.append({"term": {"node_name": node_name}})
        if source_run_id:
            filters.append({"term": {"source_run_id": source_run_id}})
        if source_llm_call_id:
            filters.append({"term": {"source_llm_call_id": source_llm_call_id}})
        if prompt_key:
            filters.append({"term": {"prompt_key": prompt_key}})
        if model:
            filters.append({"term": {"model": model}})
        if query:
            es_query = {
                "simple_query_string": {
                    "query": query,
                    "fields": ["title", "case_id", "description", "notes"],
                    "default_operator": "and",
                }
            }
            body = {
                "query": {
                    "bool": {
                        "must": [es_query],
                        "filter": filters,
                    }
                },
                "sort": [{"created_at": {"order": "desc"}}],
                "size": max(1, min(int(limit), 10000)),
                "_source": True,
            }
        else:
            body = {
                "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
                "sort": [{"created_at": {"order": "desc"}}],
                "size": max(1, min(int(limit), 10000)),
                "_source": True,
            }
        try:
            response = self.es_client.search(index=self.index_name, body=body)
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def seed_builtin_cases(self, *, force: bool = False) -> dict:
        created = []
        skipped = []
        for case in list_builtin_eval_cases():
            existing = self.get_case(case.case_id)
            if existing and not force:
                skipped.append(case.case_id)
                continue
            self.save_case(case.to_dict())
            created.append(case.case_id)
        return {"created": created, "skipped": skipped, "created_count": len(created), "skipped_count": len(skipped)}

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.index_name, EVAL_CASE_INDEX_BODY)


class EvalRunRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    @property
    def index_name(self) -> str:
        return self.settings.es_agent_eval_run_index

    def save_run(self, run: dict) -> dict:
        self._ensure_index()
        self.es_client.index_document(index=self.index_name, id=run["eval_run_id"], document=run)
        return run

    def get_run(self, eval_run_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=self.index_name, id=eval_run_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_runs(self, *, hours: int = 24, agent_name: str | None = None, limit: int = 100) -> list[dict]:
        filters: list[dict] = [{"range": {"started_at": {"gte": since_iso(hours)}}}]
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        try:
            response = self.es_client.search(
                index=self.index_name,
                body={
                    "query": {"bool": {"filter": filters}},
                    "sort": [{"started_at": {"order": "desc"}}],
                    "size": max(1, min(int(limit), 10000)),
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.index_name, EVAL_RUN_INDEX_BODY)


class BadCaseFeedbackRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    @property
    def index_name(self) -> str:
        return self.settings.es_agent_feedback_index

    def save_feedback(self, feedback: dict) -> dict:
        self._ensure_index()
        self.es_client.index_document(index=self.index_name, id=feedback["feedback_id"], document=feedback)
        return feedback

    def get_feedback(self, feedback_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=self.index_name, id=feedback_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_feedback(
        self,
        *,
        status: str | None = None,
        source_type: str | None = None,
        agent_name: str | None = None,
        severity: str | None = None,
        category: str | None = None,
        issue_type: str | None = None,
        tag: str | None = None,
        eval_run_id: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        filters: list[dict] = []
        if status:
            filters.append({"term": {"status": status}})
        if source_type:
            filters.append({"term": {"source_type": source_type}})
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        if severity:
            filters.append({"term": {"severity": severity}})
        if category:
            filters.append({"term": {"category": category}})
        if issue_type:
            filters.append({"term": {"issue_type": issue_type}})
        if tag:
            filters.append({"term": {"tags": tag}})
        if eval_run_id:
            filters.append({"term": {"eval_run_id": eval_run_id}})
        if query:
            es_query = {
                "simple_query_string": {
                    "query": query,
                    "fields": ["title", "feedback_id", "description", "notes"],
                    "default_operator": "and",
                }
            }
            body = {
                "query": {
                    "bool": {
                        "must": [es_query],
                        "filter": filters,
                    }
                },
                "sort": [{"created_at": {"order": "desc"}}],
                "size": max(1, min(int(limit), 10000)),
                "_source": True,
            }
        else:
            body = {
                "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
                "sort": [{"created_at": {"order": "desc"}}],
                "size": max(1, min(int(limit), 10000)),
                "_source": True,
            }
        try:
            response = self.es_client.search(index=self.index_name, body=body)
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.index_name, FEEDBACK_INDEX_BODY)


REGRESSION_PROFILE_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "profile_id": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "enabled": {"type": "boolean"},
            "mode": {"type": "keyword"},
            "case_tag": {"type": "keyword"},
            "severity": {"type": "keyword"},
            "category": {"type": "keyword"},
            "include_disabled": {"type": "boolean"},
            "include_judge": {"type": "boolean"},
            "include_node_eval": {"type": "boolean"},
            "node_name": {"type": "keyword"},
            "limit": {"type": "integer"},
            "gate": {"type": "object", "enabled": True},
            "trigger_policy": {"type": "object", "enabled": True},
            "notes": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "version": {"type": "integer"},
        }
    },
}


class RegressionProfileRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    @property
    def index_name(self) -> str:
        return self.settings.es_agent_regression_profile_index

    def save_profile(self, profile: dict) -> dict:
        self._ensure_index()
        self.es_client.index_document(index=self.index_name, id=profile["profile_id"], document=profile)
        return profile

    def get_profile(self, profile_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=self.index_name, id=profile_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_profiles(
        self,
        *,
        enabled: bool | None = None,
        agent_name: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        filters: list[dict] = []
        if enabled is not None:
            filters.append({"term": {"enabled": enabled}})
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        if query:
            es_query = {
                "simple_query_string": {
                    "query": query,
                    "fields": ["agent_name", "profile_id", "notes"],
                    "default_operator": "and",
                }
            }
            body = {
                "query": {
                    "bool": {
                        "must": [es_query],
                        "filter": filters,
                    }
                },
                "sort": [{"updated_at": {"order": "desc"}}],
                "size": max(1, min(int(limit), 10000)),
                "_source": True,
            }
        else:
            body = {
                "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
                "sort": [{"updated_at": {"order": "desc"}}],
                "size": max(1, min(int(limit), 10000)),
                "_source": True,
            }
        try:
            response = self.es_client.search(index=self.index_name, body=body)
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def delete_profile(self, profile_id: str) -> bool:
        try:
            self.es_client.delete(index=self.index_name, id=profile_id)
            return True
        except ESIndexNotFoundError:
            return False

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.index_name, REGRESSION_PROFILE_INDEX_BODY)


REGRESSION_GATE_REPORT_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "report_id": {"type": "keyword"},
            "mode": {"type": "keyword"},
            "trigger": {"type": "keyword"},
            "status": {"type": "keyword"},
            "ok": {"type": "boolean"},
            "dry_run": {"type": "boolean"},
            "base_ref": {"type": "keyword"},
            "head_ref": {"type": "keyword"},
            "changed_files": {"type": "keyword"},
            "impacted_agents": {"type": "keyword"},
            "recommended_agents": {"type": "keyword"},
            "executed_agents": {"type": "keyword"},
            "summary": {"type": "object", "enabled": True},
            "impact_analysis": {"type": "object", "enabled": True},
            "runs": {"type": "object", "enabled": True},
            "reasons": {"type": "keyword"},
            "created_at": {"type": "date"},
            "created_by": {"type": "keyword"},
            "git": {"type": "object", "enabled": True},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


class RegressionGateReportRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    @property
    def index_name(self) -> str:
        return self.settings.es_agent_regression_gate_report_index

    def save_report(self, report: dict) -> dict:
        self._ensure_index()
        self.es_client.index_document(index=self.index_name, id=report["report_id"], document=report)
        return report

    def get_report(self, report_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=self.index_name, id=report_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_reports(
        self,
        *,
        status: str | None = None,
        trigger: str | None = None,
        ok: bool | None = None,
        dry_run: bool | None = None,
        agent_name: str | None = None,
        hours: int = 24 * 30,
        limit: int = 100,
    ) -> list[dict]:
        filters: list[dict] = [{"range": {"created_at": {"gte": since_iso(hours)}}}]
        if status:
            filters.append({"term": {"status": status}})
        if trigger:
            filters.append({"term": {"trigger": trigger}})
        if ok is not None:
            filters.append({"term": {"ok": ok}})
        if dry_run is not None:
            filters.append({"term": {"dry_run": dry_run}})
        if agent_name:
            filters.append({
                "bool": {
                    "should": [
                        {"term": {"impacted_agents": agent_name}},
                        {"term": {"recommended_agents": agent_name}},
                        {"term": {"executed_agents": agent_name}},
                    ],
                    "minimum_should_match": 1,
                }
            })
        body = {
            "query": {"bool": {"filter": filters}},
            "sort": [{"created_at": {"order": "desc"}}],
            "size": max(1, min(int(limit), 10000)),
            "_source": True,
        }
        try:
            response = self.es_client.search(index=self.index_name, body=body)
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.index_name, REGRESSION_GATE_REPORT_INDEX_BODY)
