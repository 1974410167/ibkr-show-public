import json
import os
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.api.deps import get_longbridge_openapi_oauth_service
from app.core.config import get_settings
from app.main import app
from app.services.longbridge_openapi_oauth import (
    LongbridgeOpenAPIOAuthError,
    LongbridgeOpenAPIOAuthService,
    LongbridgeOpenAPIOAuthState,
    LongbridgeOpenAPIOAuthStore,
    OpenAPIOAuthRegistration,
    OpenAPIOAuthTokenSet,
)


class DummySettings:
    longbridge_enable = True
    longbridge_openapi_oauth_client_id = "client-id"
    longbridge_openapi_oauth_file = ""
    longbridge_openapi_oauth_scope = ""


class DummyOpenAPIOAuthRouteService:
    def status(self):
        return {
            "enabled": False,
            "configured": True,
            "oauth_connected": False,
            "client_id_configured": True,
            "client_id": "client-id",
            "has_access_token": False,
            "access_token_masked": "",
            "has_refresh_token": False,
            "refresh_token_masked": "",
            "scope": "",
            "expires_at": None,
            "expires_in_seconds": None,
            "auto_refresh_enabled": True,
            "refresh_available": False,
            "refresh_skew_seconds": 300,
            "pending_authorizations": 1,
            "last_error": "",
            "config_file": "/tmp/longbridge_openapi_oauth.json",
            "sdk_token_cache_file": "",
            "message": "Longbridge OpenAPI OAuth is not connected",
        }

    def start_authorization(self, redirect_uri, scope=None):
        return {
            "authorization_url": "https://openapi.longbridge.com/oauth2/authorize?client_id=client-id",
            "state": "state-1",
            "client_id": "client-id",
            "redirect_uri": redirect_uri,
            "scope": scope or "",
            "expires_at": 4_102_444_800,
        }


def _service(tmp_path) -> LongbridgeOpenAPIOAuthService:
    settings = DummySettings()
    settings.longbridge_openapi_oauth_file = str(tmp_path / "longbridge_openapi_oauth.json")
    return LongbridgeOpenAPIOAuthService(settings, LongbridgeOpenAPIOAuthStore(settings.longbridge_openapi_oauth_file))


def test_openapi_oauth_status_masks_tokens(tmp_path) -> None:
    service = _service(tmp_path)
    state = LongbridgeOpenAPIOAuthState(
        client_id="client-id",
        token=OpenAPIOAuthTokenSet(
            access_token="access-token-secret",
            refresh_token="refresh-token-secret",
            expires_at=4_102_444_800,
        ),
    )
    service.store.save(state)

    payload = service.status()

    assert payload["oauth_connected"] is True
    assert payload["access_token_masked"] == "****cret"
    assert payload["refresh_token_masked"] == "****cret"
    assert "access-token-secret" not in json.dumps(payload)
    assert "refresh-token-secret" not in json.dumps(payload)


def test_openapi_oauth_store_writes_0600(tmp_path) -> None:
    service = _service(tmp_path)
    service.store.save(LongbridgeOpenAPIOAuthState(client_id="client-id"))

    mode = os.stat(service.store.config_file).st_mode & 0o777
    assert mode == 0o600


def test_openapi_oauth_syncs_sdk_token_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    service = _service(tmp_path)
    state = LongbridgeOpenAPIOAuthState(
        client_id="client-id",
        token=OpenAPIOAuthTokenSet(access_token="access-token-secret", refresh_token="refresh-token-secret", expires_at=4_102_444_800),
    )

    service.sync_sdk_token_cache(state)

    cache_file = tmp_path / ".longbridge" / "openapi" / "tokens" / "client-id"
    payload = json.loads(cache_file.read_text())
    assert payload == {
        "client_id": "client-id",
        "access_token": "access-token-secret",
        "refresh_token": "refresh-token-secret",
        "expires_at": 4_102_444_800,
    }
    assert os.stat(cache_file).st_mode & 0o777 == 0o600


def test_openapi_oauth_start_route_accepts_empty_body() -> None:
    client = TestClient(app)
    app.dependency_overrides[get_longbridge_openapi_oauth_service] = lambda: DummyOpenAPIOAuthRouteService()
    try:
        _login(client)
        response = client.post("/api/admin/longbridge/openapi/oauth/start")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "state-1"
    assert payload["redirect_uri"].endswith("/api/admin/longbridge/openapi/oauth/callback")


def _login(client: TestClient) -> None:
    settings = get_settings()
    response = client.post("/api/auth/login", json={"username": settings.auth_username, "password": settings.auth_password})
    assert response.status_code == 200


class NoClientIdSettings:
    longbridge_enable = True
    longbridge_openapi_oauth_client_id = ""
    longbridge_openapi_oauth_file = ""
    longbridge_openapi_oauth_scope = ""


def _no_client_id_service(tmp_path, http_client=None) -> LongbridgeOpenAPIOAuthService:
    settings = NoClientIdSettings()
    settings.longbridge_openapi_oauth_file = str(tmp_path / "longbridge_openapi_oauth.json")
    return LongbridgeOpenAPIOAuthService(settings, LongbridgeOpenAPIOAuthStore(settings.longbridge_openapi_oauth_file), http_client=http_client)


def test_start_authorization_auto_registers_when_no_client_id(tmp_path) -> None:
    mock_http = MagicMock()
    register_response = MagicMock()
    register_response.status_code = 200
    register_response.json.return_value = {
        "client_id": "auto-registered-id",
        "client_id_issued_at": 1700000000,
        "registration_access_token": "reg-token",
        "registration_client_uri": "https://openapi.longbridge.com/oauth2/register/auto-registered-id",
        "redirect_uris": ["https://example.com/callback"],
    }
    register_response.raise_for_status = MagicMock()
    mock_http.post.return_value = register_response

    service = _no_client_id_service(tmp_path, http_client=mock_http)
    result = service.start_authorization("https://example.com/callback")

    assert "auto-registered-id" in result["authorization_url"]
    assert result["client_id"] == "auto-registered-id"

    state = service.store.read()
    assert state.client_id == "auto-registered-id"
    assert state.registration is not None
    assert state.registration.client_id == "auto-registered-id"
    assert state.registration.registration_access_token == "reg-token"


def test_start_authorization_does_not_re_register_when_client_id_exists(tmp_path) -> None:
    mock_http = MagicMock()
    service = _no_client_id_service(tmp_path, http_client=mock_http)

    state = LongbridgeOpenAPIOAuthState(
        client_id="existing-id",
        registration=OpenAPIOAuthRegistration(client_id="existing-id"),
    )
    service.store.save(state)

    result = service.start_authorization("https://example.com/callback")

    assert result["client_id"] == "existing-id"
    mock_http.post.assert_not_called()


def test_register_oauth_client_failure_raises_clear_error(tmp_path) -> None:
    mock_http = MagicMock()
    error_response = MagicMock()
    error_response.status_code = 400
    error_response.json.return_value = {"error": "invalid_client_metadata", "error_description": "Invalid redirect URI"}
    error_response.raise_for_status = MagicMock(side_effect=Exception("400 Bad Request"))
    mock_http.post.return_value = error_response

    service = _no_client_id_service(tmp_path, http_client=mock_http)

    import pytest
    with pytest.raises(LongbridgeOpenAPIOAuthError):
        service.register_oauth_client("https://example.com/callback")


def test_env_client_id_takes_priority_over_registration(tmp_path) -> None:
    class EnvSettings:
        longbridge_enable = True
        longbridge_openapi_oauth_client_id = "env-client-id"
        longbridge_openapi_oauth_file = ""
        longbridge_openapi_oauth_scope = ""

    settings = EnvSettings()
    settings.longbridge_openapi_oauth_file = str(tmp_path / "longbridge_openapi_oauth.json")
    service = LongbridgeOpenAPIOAuthService(settings, LongbridgeOpenAPIOAuthStore(settings.longbridge_openapi_oauth_file))

    state = LongbridgeOpenAPIOAuthState(
        client_id="stored-id",
        registration=OpenAPIOAuthRegistration(client_id="registered-id"),
    )
    service.store.save(state)

    assert service._client_id(service.store.read()) == "env-client-id"


def test_complete_authorization_unaffected_by_registration(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    mock_http = MagicMock()
    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "read",
    }
    token_response.raise_for_status = MagicMock()
    mock_http.post.return_value = token_response

    service = _no_client_id_service(tmp_path, http_client=mock_http)

    from app.services.longbridge_openapi_oauth import OpenAPIOAuthPendingState
    import time
    now = int(time.time())
    state = LongbridgeOpenAPIOAuthState(
        client_id="auto-id",
        registration=OpenAPIOAuthRegistration(client_id="auto-id"),
        pending_states={
            "test-state": OpenAPIOAuthPendingState(
                state="test-state",
                code_verifier="verifier",
                redirect_uri="https://example.com/callback",
                scope="read",
                created_at=now,
                expires_at=now + 900,
            ),
        },
    )
    service.store.save(state)

    result = service.complete_authorization("auth-code", "test-state")

    assert result["oauth_connected"] is True
    saved = service.store.read()
    assert saved.token.access_token == "new-access"
    assert saved.registration is not None
    assert saved.registration.client_id == "auto-id"


def test_status_api_returns_auto_registered_fields() -> None:
    class StatusWithRegistration:
        def status(self):
            return {
                "enabled": True,
                "configured": True,
                "oauth_connected": True,
                "client_id_configured": True,
                "client_id": "auto-registered-id",
                "has_access_token": True,
                "access_token_masked": "****",
                "has_refresh_token": True,
                "refresh_token_masked": "****",
                "scope": "read",
                "expires_at": 4_102_444_800,
                "expires_in_seconds": 3600,
                "auto_refresh_enabled": True,
                "refresh_available": True,
                "refresh_skew_seconds": 300,
                "pending_authorizations": 0,
                "last_error": "",
                "config_file": "/tmp/test.json",
                "sdk_token_cache_file": "/tmp/tokens/auto-registered-id",
                "auto_registered": True,
                "registration_client_uri": "https://openapi.longbridge.com/oauth2/register/auto-registered-id",
                "message": "Longbridge OpenAPI OAuth is connected",
            }

    client = TestClient(app)
    app.dependency_overrides[get_longbridge_openapi_oauth_service] = lambda: StatusWithRegistration()
    try:
        _login(client)
        response = client.get("/api/admin/longbridge/openapi/oauth/status")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["auto_registered"] is True
    assert payload["registration_client_uri"] == "https://openapi.longbridge.com/oauth2/register/auto-registered-id"
