"""Tests for market event credential store."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.services.config_crypto import ConfigCryptoError, is_encrypted_token
from app.services.market_event_credential import (
    MarketEventCredentialStore,
    mask_api_key,
    is_masked_api_key,
)


# ---------------------------------------------------------------------------
# Masking tests
# ---------------------------------------------------------------------------


def test_mask_api_key_long():
    result = mask_api_key("abcdef123456")
    assert result == "****3456"


def test_mask_api_key_short():
    result = mask_api_key("abc")
    assert result == "****"


def test_mask_api_key_empty():
    assert mask_api_key("") == ""
    assert mask_api_key(None) == ""


def test_is_masked_api_key():
    assert is_masked_api_key("****3456") is True
    assert is_masked_api_key("real-key") is False
    assert is_masked_api_key(None) is False
    assert is_masked_api_key("") is False


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------


def _make_store() -> tuple[MarketEventCredentialStore, Path]:
    tmpdir = tempfile.mkdtemp()
    config_file = Path(tmpdir) / "test_credentials.json"
    return MarketEventCredentialStore(str(config_file), "unit-test-encryption-key"), config_file


def test_save_and_read_credential():
    store, _ = _make_store()
    entry = store.save_credential("BLS", "api_key", "my-secret-key-1234")
    assert entry.source_code == "BLS"
    assert entry.masked_value == "****1234"

    retrieved = store.get_credential("BLS")
    assert retrieved is not None
    assert retrieved.value != "my-secret-key-1234"
    assert is_encrypted_token(retrieved.value)
    assert retrieved.masked_value == "****1234"


def test_get_decrypted_value():
    store, _ = _make_store()
    store.save_credential("BLS", "api_key", "test-key")
    value = store.get_decrypted_value("BLS", "api_key")
    assert value == "test-key"


def test_get_decrypted_value_missing():
    store, _ = _make_store()
    assert store.get_decrypted_value("BLS") is None


def test_delete_credential():
    store, _ = _make_store()
    store.save_credential("BLS", "api_key", "test-key")
    assert store.delete_credential("BLS") is True
    assert store.get_credential("BLS") is None


def test_delete_credential_not_found():
    store, _ = _make_store()
    assert store.delete_credential("NONEXISTENT") is False


def test_list_credentials():
    store, _ = _make_store()
    store.save_credential("BLS", "api_key", "key1")
    store.save_credential("BEA", "api_key", "key2")
    entries = store.list_credentials()
    codes = [e.source_code for e in entries]
    assert "BLS" in codes
    assert "BEA" in codes


def test_update_existing_credential():
    store, _ = _make_store()
    store.save_credential("BLS", "api_key", "old-key")
    store.save_credential("BLS", "api_key", "new-key-5678")
    entry = store.get_credential("BLS")
    assert entry is not None
    assert entry.value != "new-key-5678"
    assert is_encrypted_token(entry.value)
    assert entry.masked_value == "****5678"


def test_saved_credential_file_does_not_contain_plaintext_bls_api_key():
    store, config_file = _make_store()
    raw_key = "bls-secret-key-never-on-disk-1234"
    store.save_credential("BLS", "api_key", raw_key)
    payload = config_file.read_text(encoding="utf-8")
    assert raw_key not in payload
    assert "****1234" in payload


def test_credential_file_permissions(tmp_path):
    config_file = tmp_path / "cred.json"
    store = MarketEventCredentialStore(str(config_file), "unit-test-encryption-key")
    store.save_credential("BLS", "api_key", "test")
    # File should exist
    assert config_file.exists()


def test_save_requires_config_encryption_key(tmp_path, monkeypatch):
    monkeypatch.delenv("CONFIG_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    store = MarketEventCredentialStore(str(tmp_path / "cred.json"))
    with pytest.raises(ConfigCryptoError):
        store.save_credential("BLS", "api_key", "test")


def test_empty_file_returns_empty():
    store, _ = _make_store()
    assert store.list_credentials() == []
    assert store.get_credential("BLS") is None
