from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.longbridge_openapi_oauth import LongbridgeOpenAPIOAuthService, LongbridgeOpenAPIOAuthStore
from app.services.longbridge_service import LongbridgeExternalDataClient, LongbridgeUnavailableError, _to_iso_datetime, _to_json_value, normalize_longbridge_symbol

client = TestClient(app)


def test_normalize_longbridge_symbol_defaults_plain_ticker_to_us() -> None:
    assert normalize_longbridge_symbol("AAPL") == "AAPL.US"
    assert normalize_longbridge_symbol("AAPL.US") == "AAPL.US"
    assert normalize_longbridge_symbol("QQQ") == "QQQ.US"
    assert normalize_longbridge_symbol("700.HK") == "700.HK"


def test_longbridge_health_returns_not_configured_when_openapi_client_id_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("LONGBRIDGE_OPENAPI_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.setenv("LONGBRIDGE_OPENAPI_OAUTH_FILE", str(tmp_path / "longbridge_oauth.json"))
    monkeypatch.setenv("LONGBRIDGE_ENABLE", "true")
    get_settings.cache_clear()

    response = client.get("/api/longbridge/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["configured"] is False
    assert payload["sdk_loaded"] is True
    assert payload["oauth_connected"] is False
    assert payload["message"] == "Longbridge OpenAPI OAuth client_id is not configured"
    get_settings.cache_clear()


def test_longbridge_json_serializer_handles_non_dict_vars() -> None:
    class WeirdSdkObject:
        @property
        def __dict__(self):
            return list.append

        value = "ok"

    payload = _to_json_value(WeirdSdkObject())

    assert payload["value"] == "ok"


def test_longbridge_json_serializer_collapses_sdk_enums() -> None:
    FakeEnum = type("SecurityBoard", (), {"__module__": "builtins", "__str__": lambda self: "SecurityBoard.USMain"})

    assert _to_json_value(FakeEnum()) == "SecurityBoard.USMain"


def test_search_macro_news_uses_longbridge_cli_json(monkeypatch) -> None:
    class DummySettings:
        longbridge_enable = True
        longbridge_openapi_oauth_client_id = ""
        longbridge_openapi_oauth_file = ""
        longbridge_openapi_oauth_scope = ""

    class Completed:
        stdout = '[{"title":"Fed decision","summary":"Rates unchanged","url":"https://example.com","published_at":"2026-05-01T00:00:00Z"}]'

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return Completed()

    monkeypatch.setattr("app.services.longbridge_service.subprocess.run", fake_run)
    client_service = LongbridgeExternalDataClient(DummySettings())

    response = client_service.search_macro_news(keyword="Fed", limit=5)

    assert calls[0][:4] == ["longbridge", "news", "search", "Fed"]
    assert response.keyword == "Fed"
    assert response.items[0].title == "Fed decision"


def test_business_call_requires_openapi_oauth_token(tmp_path) -> None:
    class DummySettings:
        longbridge_enable = True
        longbridge_openapi_oauth_client_id = "client-id"
        longbridge_openapi_oauth_file = str(tmp_path / "longbridge_openapi_oauth.json")
        longbridge_openapi_oauth_scope = ""

    settings = DummySettings()
    oauth_service = LongbridgeOpenAPIOAuthService(settings, LongbridgeOpenAPIOAuthStore(settings.longbridge_openapi_oauth_file))
    client_service = LongbridgeExternalDataClient(settings, oauth_service)

    try:
        client_service.get_quote_snapshot("AAPL")
    except LongbridgeUnavailableError as exc:
        assert "Longbridge OpenAPI OAuth authorization is required" in str(exc)
    else:
        raise AssertionError("Expected LongbridgeUnavailableError")


def test_to_iso_datetime_treats_epoch_zero_as_unknown() -> None:
    assert _to_iso_datetime(0) == ""
    assert _to_iso_datetime("0") == ""
    assert _to_iso_datetime("1970-01-01T00:00:00") == ""


def test_to_iso_datetime_converts_valid_timestamp() -> None:
    assert _to_iso_datetime(1714521600).startswith("2024-05-01")


def test_to_iso_datetime_preserves_valid_iso_text() -> None:
    assert _to_iso_datetime("2026-05-01T12:30:00Z") == "2026-05-01T12:30:00Z"
