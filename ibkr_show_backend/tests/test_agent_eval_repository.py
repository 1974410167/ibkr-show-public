from app.services.agent_eval_repository import EvalCaseRepository


class _Settings:
    es_agent_eval_case_index = "eval_cases_test"


class _FakeES:
    def __init__(self) -> None:
        self.search_body = None

    def search(self, *, index: str, body: dict) -> dict:
        self.search_body = body
        return {"hits": {"hits": []}}

    def create_index_if_missing(self, index: str, body: dict) -> None:
        pass


def _filters(body: dict) -> list[dict]:
    query = body["query"]
    return query.get("bool", {}).get("filter", [])


def test_list_cases_enabled_true_includes_missing_enabled_and_excludes_archived_by_default() -> None:
    es = _FakeES()
    repo = EvalCaseRepository(es, _Settings())

    repo.list_cases(enabled=True)

    filters = _filters(es.search_body)
    assert {
        "bool": {
            "should": [
                {"term": {"enabled": True}},
                {"bool": {"must_not": {"exists": {"field": "enabled"}}}},
            ],
            "minimum_should_match": 1,
        }
    } in filters
    assert {
        "bool": {
            "should": [
                {"term": {"archived": False}},
                {"bool": {"must_not": {"exists": {"field": "archived"}}}},
            ],
            "minimum_should_match": 1,
        }
    } in filters


def test_list_cases_enabled_false_matches_only_explicit_disabled() -> None:
    es = _FakeES()
    repo = EvalCaseRepository(es, _Settings())

    repo.list_cases(enabled=False, include_archived=True)

    filters = _filters(es.search_body)
    assert {"term": {"enabled": False}} in filters
    assert not any("archived" in str(item) for item in filters)
