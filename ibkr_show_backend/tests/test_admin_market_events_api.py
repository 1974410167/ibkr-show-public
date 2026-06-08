from fastapi.testclient import TestClient

from app.api import deps
from app.api.routes import admin_market_events
from app.api.routes.admin_market_events import _get_admin_service
from app.api.deps import require_admin_session
from app.main import app
from app.services.market_event_admin_service import MarketEventAdminError


class _FakeAdminMarketEventService:
    def list_sources(self):
        return [
            {
                "source_code": "BLS",
                "source_name": "BLS",
                "description": "Inflation data",
                "enabled": True,
                "priority": 100,
                "apply_url": None,
                "doc_url": None,
                "requires_api_key": True,
                "credential_key_name": "api_key",
                "credential_configured": False,
                "masked_value": None,
                "last_check_at": None,
                "last_check_status": None,
                "last_error": None,
                "updated_at": None,
            }
        ]


class _FailingCredentialAdminMarketEventService(_FakeAdminMarketEventService):
    def save_credential(self, source_code, credential_key, value):
        raise MarketEventAdminError("CONFIG_ENCRYPTION_KEY or APP_SECRET_KEY must be configured")


def test_admin_market_event_sources_route_serializes_authenticated_response() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[_get_admin_service] = lambda: _FakeAdminMarketEventService()
    client = TestClient(app)

    try:
        response = client.get("/api/admin/market-events/sources")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["source_code"] == "BLS"


def test_admin_market_event_save_credential_config_error_returns_400() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[_get_admin_service] = lambda: _FailingCredentialAdminMarketEventService()
    client = TestClient(app)

    try:
        response = client.put(
            "/api/admin/market-events/sources/BLS/credential",
            json={"credential_key": "api_key", "value": "secret-value"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "CONFIG_ENCRYPTION_KEY" in response.json()["detail"]


def test_admin_market_event_dependency_factories_use_no_arg_es_client(monkeypatch) -> None:
    settings = object()
    es_client = object()

    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_es_client", lambda: es_client)
    monkeypatch.setattr(
        admin_market_events,
        "MarketEventAdminService",
        lambda client, config: ("admin", client, config),
    )
    monkeypatch.setattr(
        admin_market_events,
        "MarketEventQueryService",
        lambda client, config: ("query", client, config),
    )

    assert admin_market_events._get_admin_service() == ("admin", es_client, settings)
    assert admin_market_events._get_query_service() == ("query", es_client, settings)
