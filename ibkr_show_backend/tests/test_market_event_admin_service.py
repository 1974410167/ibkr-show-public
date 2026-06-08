"""Tests for market event admin service compatibility handling."""

from __future__ import annotations

import pytest

from app.schemas.market_event import ProviderHealthCheckResult
from app.services import market_event_providers
from app.services.config_crypto import ConfigCryptoError
from app.services.market_event_admin_service import MarketEventAdminError, MarketEventAdminService


class _FakeRepo:
    def __init__(self):
        self.updates = []

    def get_source(self, source_code):
        if source_code == "BLS":
            return self.list_sources()[0]
        return None

    def update_source(self, source_code, updates):
        self.updates.append((source_code, updates))

    def list_sources(self):
        return [
            {
                "source_code": "bls",
                "source_name": None,
                "description": None,
                "enabled": "true",
                "priority": "",
                "requires_api_key": True,
                "credential_key_name": "BLS_API_KEY",
                "apply_url": 123,
                "doc_url": "",
                "last_check_at": "not-a-date",
                "last_check_status": "unknown",
                "last_error": 456,
                "updated_at": "",
            },
            {
                "source_code": "UNKNOWN_SOURCE",
                "source_name": "Unknown",
            },
        ]


class _FakeCredentialStore:
    def __init__(self):
        self.saved = []
        self.deleted = []
        self.decrypted = {}

    def list_credentials(self):
        return []

    def save_credential(self, source_code, credential_key, value):
        self.saved.append((source_code, credential_key, value))

    def delete_credential(self, source_code, credential_key):
        self.deleted.append((source_code, credential_key))
        return True

    def get_decrypted_value(self, source_code, credential_key):
        return self.decrypted.get((source_code, credential_key))


class _FailingCredentialStore:
    def list_credentials(self):
        raise RuntimeError("credential metadata unreadable")


class _CryptoFailingCredentialStore:
    def list_credentials(self):
        return []

    def save_credential(self, source_code, credential_key, value):
        raise ConfigCryptoError("CONFIG_ENCRYPTION_KEY or APP_SECRET_KEY must be configured")


def test_admin_list_sources_sanitizes_legacy_blank_fields() -> None:
    service = MarketEventAdminService.__new__(MarketEventAdminService)
    service._repo = _FakeRepo()
    service._cred_store = _FakeCredentialStore()
    service.initialize_indices = lambda: None

    result = service.list_sources()

    assert len(result) == 1
    source = result[0]
    assert source.source_code == "BLS"
    assert source.source_name == ""
    assert source.description == ""
    assert source.enabled is True
    assert source.priority == 100
    assert source.credential_key_name == "BLS_API_KEY"
    assert source.apply_url == "123"
    assert source.doc_url is None
    assert source.last_check_at is None
    assert source.last_check_status is None
    assert source.last_error == "456"
    assert source.updated_at is None


def test_admin_list_sources_does_not_fail_when_credential_metadata_is_unreadable() -> None:
    service = MarketEventAdminService.__new__(MarketEventAdminService)
    service._repo = _FakeRepo()
    service._cred_store = _FailingCredentialStore()
    service.initialize_indices = lambda: None

    result = service.list_sources()

    assert len(result) == 1
    assert result[0].source_code == "BLS"
    assert result[0].credential_configured is False
    assert result[0].masked_value is None


def test_admin_save_credential_reports_missing_encryption_key_as_admin_error() -> None:
    service = MarketEventAdminService.__new__(MarketEventAdminService)
    service._repo = _FakeRepo()
    service._cred_store = _CryptoFailingCredentialStore()
    service.initialize_indices = lambda: None

    with pytest.raises(MarketEventAdminError) as exc_info:
        service.save_credential("BLS", "api_key", "secret-value")

    assert "CONFIG_ENCRYPTION_KEY" in str(exc_info.value)


def test_admin_save_credential_uses_source_configured_credential_key() -> None:
    service = MarketEventAdminService.__new__(MarketEventAdminService)
    service._repo = _FakeRepo()
    cred_store = _FakeCredentialStore()
    service._cred_store = cred_store
    service.initialize_indices = lambda: None

    service.save_credential("BLS", "api_key", "secret-value")

    assert cred_store.saved == [("BLS", "BLS_API_KEY", "secret-value")]


def test_admin_delete_credential_uses_source_configured_key_and_cleans_legacy_key() -> None:
    service = MarketEventAdminService.__new__(MarketEventAdminService)
    service._repo = _FakeRepo()
    cred_store = _FakeCredentialStore()
    service._cred_store = cred_store
    service.initialize_indices = lambda: None

    service.delete_credential("BLS")

    assert cred_store.deleted == [("BLS", "BLS_API_KEY"), ("BLS", "api_key")]


class _FakeHealthProvider:
    async def health_check(self):
        return ProviderHealthCheckResult(
            source_code="BLS",
            provider_name="bls",
            status="SUCCESS",
            message="BLS API reachable",
        )


class _FakeProviderRegistry:
    def __init__(self, repo, cred_store):
        self.repo = repo
        self.cred_store = cred_store

    def get_provider(self, source_code):
        return _FakeHealthProvider()


def test_admin_test_source_uses_provider_health_check_and_updates_status(monkeypatch) -> None:
    repo = _FakeRepo()
    service = MarketEventAdminService.__new__(MarketEventAdminService)
    service._repo = repo
    cred_store = _FakeCredentialStore()
    cred_store.decrypted[("BLS", "BLS_API_KEY")] = "secret-value"
    service._cred_store = cred_store
    service.initialize_indices = lambda: None
    monkeypatch.setattr(market_event_providers, "MarketEventProviderRegistry", _FakeProviderRegistry)

    result = service.test_source("BLS")

    assert result.source_code == "BLS"
    assert result.status == "SUCCESS"
    assert result.message == "BLS API reachable"
    assert repo.updates
    assert repo.updates[0][0] == "BLS"
    assert repo.updates[0][1]["last_check_status"] == "SUCCESS"
