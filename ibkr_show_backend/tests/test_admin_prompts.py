from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.agents.prompt_registry import get_prompt_definition, list_prompt_definitions
from app.api.deps import get_admin_prompt_service, require_admin_session
from app.core.auth import AuthSession
from app.core.config import get_settings
from app.main import app
from app.services.admin_prompt_repository import content_sha256
from app.services.admin_prompt_repository import AdminPromptRepository
from app.services.admin_prompt_service import AdminPromptService, PromptNotFoundError


EXPECTED_PROMPT_KEYS = {
    "account_copilot_planner",
    "daily_position_review_main",
    "daily_symbol_evidence_card",
    "daily_macro_evidence_card",
    "trade_review_main",
    "trade_review_behavior_pattern",
    "trade_review_opportunity_cost",
    "trade_decision_market_trend",
    "trade_decision_fundamental_valuation",
    "trade_decision_event_catalyst",
    "trade_decision_bull_thesis",
    "trade_decision_bear_thesis",
    "trade_decision_bull_rebuttal",
    "trade_decision_bear_rebuttal",
    "trade_decision_debate_judge",
    "trade_decision_ai_policy_assessment",
    "trade_decision_trade_plan",
}


@dataclass
class DummySettings:
    es_agent_prompt_index: str = "agent-prompts-index"


class StubPromptESClient:
    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}

    def create_index_if_missing(self, index: str, body: dict) -> None:
        return None

    def index_document(self, index: str, id: str, document: dict) -> dict:
        self.documents[id] = dict(document)
        return {"result": "created"}

    def get(self, index: str, id: str) -> dict | None:
        document = self.documents.get(id)
        return {"_source": dict(document)} if document else None

    def search(self, index: str, body: dict) -> dict:
        values = list(self.documents.values())
        filters = body.get("query", {}).get("bool", {}).get("filter", [])
        for item in filters:
            term = item.get("term", {})
            for key, expected in term.items():
                values = [document for document in values if document.get(key) == expected]
        sort = body.get("sort", [])
        if sort:
            field, config = next(iter(sort[0].items()))
            values.sort(key=lambda item: item.get(field) or "", reverse=config.get("order") == "desc")
        size = body.get("size", len(values))
        return {"hits": {"hits": [{"_source": dict(item)} for item in values[:size]]}}

    def update_by_query(self, index: str, body: dict) -> dict:
        filters = body.get("query", {}).get("bool", {}).get("filter", [])
        updated = 0
        updated_at = body.get("script", {}).get("params", {}).get("updated_at")
        for document in self.documents.values():
            matches = True
            for item in filters:
                term = item.get("term", {})
                for key, expected in term.items():
                    if document.get(key) != expected:
                        matches = False
            if matches:
                document["status"] = "archived"
                document["updated_at"] = updated_at
                updated += 1
        return {"updated": updated}


def _service() -> AdminPromptService:
    return AdminPromptService(AdminPromptRepository(StubPromptESClient(), DummySettings()))


def _login(client: TestClient) -> None:
    settings = get_settings()
    response = client.post(
        "/api/auth/login",
        json={"username": settings.auth_username, "password": settings.auth_password},
    )
    assert response.status_code == 200


def test_prompt_registry_contains_expected_keys() -> None:
    definitions = list_prompt_definitions()

    assert {definition.prompt_key for definition in definitions} == EXPECTED_PROMPT_KEYS
    assert len(definitions) == 17
    for definition in definitions:
        assert definition.default_content.strip()
        assert get_prompt_definition(definition.prompt_key) is definition


def test_prompt_defaults_are_chinese_and_optimized() -> None:
    definitions = {definition.prompt_key: definition for definition in list_prompt_definitions()}

    for definition in definitions.values():
        content = definition.default_content
        assert content.strip()
        chinese_chars = sum(1 for char in content if "\u4e00" <= char <= "\u9fff")
        ascii_letters = sum(1 for char in content if char.isascii() and char.isalpha())
        assert chinese_chars > ascii_letters * 0.25

    account_prompt = definitions["account_copilot_planner"].default_content
    assert "You are Account Copilot" not in account_prompt
    assert "事实优先级" in account_prompt
    assert "request_skill_approval" in account_prompt

    behavior_prompt = definitions["trade_review_behavior_pattern"].default_content
    opportunity_prompt = definitions["trade_review_opportunity_cost"].default_content
    assert len(behavior_prompt) > 300
    assert len(opportunity_prompt) > 300
    for field in ("behavior_summary", "recurring_patterns", "improvement_notes", "confidence", "data_limitations"):
        assert field in behavior_prompt
    for field in ("opportunity_cost_summary", "missed_upside", "capital_redeployment", "alternative_actions", "data_limitations"):
        assert field in opportunity_prompt

    for key in (
        "trade_decision_bull_thesis",
        "trade_decision_bear_thesis",
        "trade_decision_bull_rebuttal",
        "trade_decision_bear_rebuttal",
        "trade_decision_debate_judge",
        "trade_decision_trade_plan",
    ):
        prompt = definitions[key].default_content
        assert "输出示例" in prompt
        assert "data_limitations" in prompt


def test_seed_defaults_creates_active_default_versions() -> None:
    service = _service()

    seeded = service.seed_default_versions()
    items = service.list_prompts()

    assert len(seeded) == 17
    assert {item["prompt_key"] for item in seeded} == EXPECTED_PROMPT_KEYS
    assert all(item["version"] == "v1" for item in seeded)
    assert all(item["status"] == "active" for item in seeded)
    assert all(item["is_default"] is True for item in seeded)
    assert all(item["has_active"] is True for item in items)
    assert all(item["is_default_active"] is True for item in items)
    assert all(item["matches_code_default"] is True for item in items)
    assert all(item["is_code_default_outdated"] is False for item in items)
    assert all(item["code_default_hash"] == item["active_content_hash"] for item in items)


def test_create_version_does_not_replace_active() -> None:
    service = _service()
    service.seed_default_versions()

    created = service.create_version(
        "trade_review_main",
        payload=type("Payload", (), {"content": "new prompt", "change_note": "draft"})(),
        created_by="tester",
    )
    detail = service.get_prompt_detail("trade_review_main")

    assert created["version"] == "v2"
    assert created["status"] == "draft"
    assert detail["active"]["version"] == "v1"
    assert [item["status"] for item in detail["versions"]] == ["active", "draft"]


def test_create_version_from_code_default_creates_draft_without_changing_active() -> None:
    service = _service()
    active = service.create_version(
        "account_copilot_planner",
        payload=type("Payload", (), {"content": "旧的后台 active prompt", "change_note": None})(),
        created_by="tester",
    )
    service.activate_version("account_copilot_planner", active["version"], activated_by="tester")

    created, message = service.create_version_from_code_default("account_copilot_planner", created_by="tester")
    detail = service.get_prompt_detail("account_copilot_planner")
    list_item = next(item for item in service.list_prompts() if item["prompt_key"] == "account_copilot_planner")

    assert created is not None
    assert created["status"] == "draft"
    assert created["is_default"] is False
    assert created["content_hash"] == list_item["code_default_hash"]
    assert "code default" in message
    assert detail["active"]["version"] == "v1"
    assert detail["active"]["content_hash"] != list_item["code_default_hash"]
    assert list_item["matches_code_default"] is False
    assert list_item["is_code_default_outdated"] is True
    assert {item["version"]: item["status"] for item in detail["versions"]} == {"v1": "active", "v2": "draft"}


def test_list_prompts_marks_custom_active_as_outdated() -> None:
    service = _service()
    active = service.create_version(
        "trade_review_main",
        payload=type("Payload", (), {"content": "旧的自定义 active prompt", "change_note": None})(),
        created_by="tester",
    )
    service.activate_version("trade_review_main", active["version"], activated_by="tester")

    item = next(item for item in service.list_prompts() if item["prompt_key"] == "trade_review_main")

    assert item["active_content_hash"] == content_sha256("旧的自定义 active prompt")
    assert item["active_content_hash"] != item["code_default_hash"]
    assert item["is_default_active"] is False
    assert item["matches_code_default"] is False
    assert item["is_code_default_outdated"] is True


def test_sync_code_defaults_creates_drafts_without_auto_activation() -> None:
    service = _service()
    active = service.create_version(
        "trade_review_main",
        payload=type("Payload", (), {"content": "旧交易复盘 prompt", "change_note": None})(),
        created_by="tester",
    )
    service.activate_version("trade_review_main", active["version"], activated_by="tester")

    result = service.sync_code_default_versions(created_by="tester")
    detail = service.get_prompt_detail("trade_review_main")

    assert result["created"]
    assert detail["active"]["version"] == "v1"
    assert any(item["status"] == "draft" for item in detail["versions"])


def test_activate_version_archives_previous_active() -> None:
    service = _service()
    service.seed_default_versions()
    service.create_version(
        "trade_review_main",
        payload=type("Payload", (), {"content": "new prompt", "change_note": None})(),
        created_by="tester",
    )

    activated = service.activate_version("trade_review_main", "v2", activated_by="tester")
    detail = service.get_prompt_detail("trade_review_main")

    assert activated["status"] == "active"
    assert activated["version"] == "v2"
    statuses = {item["version"]: item["status"] for item in detail["versions"]}
    assert statuses == {"v1": "archived", "v2": "active"}


def test_runtime_prompt_falls_back_to_code_default_without_admin_active() -> None:
    service = _service()

    runtime = service.get_runtime_prompt("daily_macro_evidence_card")

    assert runtime["metadata"]["source"] == "code_default"
    assert runtime["metadata"]["content_hash"]
    assert runtime["content"] == get_prompt_definition("daily_macro_evidence_card").default_content


def test_unknown_prompt_key_raises_reasonable_error() -> None:
    service = _service()

    try:
        service.get_prompt_detail("missing_prompt")
    except PromptNotFoundError as exc:
        assert "missing_prompt" in str(exc)
    else:
        raise AssertionError("Expected PromptNotFoundError")


def test_admin_prompt_routes_return_404_and_422() -> None:
    client = TestClient(app)
    service = _service()
    app.dependency_overrides[get_admin_prompt_service] = lambda: service
    app.dependency_overrides[require_admin_session] = lambda: AuthSession(username="tester", expires_at=4_102_444_800)

    try:
        missing_response = client.get("/api/admin/prompts/missing_prompt")
        empty_response = client.post(
            "/api/admin/prompts/trade_review_main/versions",
            json={"content": "   "},
        )
    finally:
        app.dependency_overrides.clear()

    assert missing_response.status_code == 404
    assert empty_response.status_code == 422
