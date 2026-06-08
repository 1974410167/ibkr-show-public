"""Market Event admin service -- source config, credential management, test connection."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.clients.es_client import ElasticsearchClient
from app.core.config import Settings
from app.schemas.market_event import (
    MarketEventSourceConfigResponse,
    MarketEventSourceTestResponse,
    MarketEventTestStatus,
)
from app.services.config_crypto import ConfigCryptoError
from app.services.market_event_credential import MarketEventCredentialStore
from app.services.market_event_index import ensure_market_event_indices
from app.services.market_event_repository import MarketEventRepository

logger = logging.getLogger(__name__)

VALID_SOURCE_CODES = {"BLS", "BEA", "FRED", "FED", "ISM", "LONGBRIDGE", "MANUAL", "SYSTEM"}
VALID_TEST_STATUSES = {"SUCCESS", "FAILED", "SKIPPED"}


class MarketEventAdminError(ValueError):
    """Raised when admin operations fail."""


def _clean_optional(value: Any) -> Any | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _clean_optional_str(value: Any) -> str | None:
    value = _clean_optional(value)
    if value is None:
        return None
    return str(value)


def _clean_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _clean_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _clean_int(value: Any, default: int = 100) -> int:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_datetime(value: Any) -> Any | None:
    value = _clean_optional(value)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        try:
            datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Ignoring invalid market event source datetime")
            return None
        return normalized
    return None


def _clean_test_status(value: Any) -> MarketEventTestStatus | None:
    normalized = str(value or "").strip().upper()
    if normalized in VALID_TEST_STATUSES:
        return normalized  # type: ignore[return-value]
    return None


def _clean_source_code(value: Any) -> str | None:
    normalized = str(value or "").strip().upper()
    if normalized in VALID_SOURCE_CODES:
        return normalized
    return None


def _masked_credential_map(cred_store: MarketEventCredentialStore) -> dict[tuple[str, str], str]:
    try:
        credentials = cred_store.list_credentials()
    except Exception:
        logger.exception("Failed to read market event credential metadata")
        return {}

    result: dict[tuple[str, str], str] = {}
    for credential in credentials:
        code = _clean_source_code(credential.source_code)
        key = _clean_str(credential.credential_key or "api_key", "api_key")
        if code and key and credential.value:
            result[(code, key)] = _clean_optional(credential.masked_value) or "****"
    return result


class MarketEventAdminService:
    """Admin operations for market event data sources."""

    def __init__(
        self,
        es_client: ElasticsearchClient,
        settings: Settings,
    ) -> None:
        self._es = es_client
        self._s = settings
        self._repo = MarketEventRepository(es_client, settings)
        self._cred_store = MarketEventCredentialStore(
            settings.market_event_credential_file,
            settings.config_encryption_key,
        )

    def initialize_indices(self) -> None:
        """Create ES indices if missing and seed default sources."""
        ensure_market_event_indices(self._es)
        self._repo.seed_sources()

    def list_sources(self) -> list[MarketEventSourceConfigResponse]:
        """List all data source configurations."""
        self.initialize_indices()
        sources = self._repo.list_sources()
        cred_map = _masked_credential_map(self._cred_store)

        result = []
        for src in sources:
            code = _clean_source_code(src.get("source_code"))
            if not code:
                logger.warning("Skipping invalid market event source_code in admin list")
                continue
            cred_key = _clean_optional_str(src.get("credential_key_name"))
            masked_value = cred_map.get((code, cred_key)) if cred_key else None

            result.append(MarketEventSourceConfigResponse(
                source_code=code,
                source_name=_clean_str(src.get("source_name")),
                description=_clean_str(src.get("description")),
                enabled=_clean_bool(src.get("enabled"), True),
                priority=_clean_int(src.get("priority"), 100),
                apply_url=_clean_optional_str(src.get("apply_url")),
                doc_url=_clean_optional_str(src.get("doc_url")),
                requires_api_key=_clean_bool(src.get("requires_api_key"), False),
                credential_key_name=cred_key,
                credential_configured=masked_value is not None,
                masked_value=masked_value,
                last_check_at=_clean_datetime(src.get("last_check_at")),
                last_check_status=_clean_test_status(src.get("last_check_status")),
                last_error=_clean_optional_str(src.get("last_error")),
                updated_at=_clean_datetime(src.get("updated_at")),
            ))
        return result

    def get_source(self, source_code: str) -> MarketEventSourceConfigResponse:
        """Get a single source configuration."""
        self.initialize_indices()
        src = self._repo.get_source(source_code)
        if not src:
            raise MarketEventAdminError(f"Source {source_code} not found")

        code = _clean_source_code(source_code)
        if not code:
            raise MarketEventAdminError(f"Source {source_code} not found")
        cred_key = _clean_optional_str(src.get("credential_key_name"))
        masked_value = None
        if cred_key:
            masked_value = _masked_credential_map(self._cred_store).get((code, cred_key))

        return MarketEventSourceConfigResponse(
            source_code=code,
            source_name=_clean_str(src.get("source_name")),
            description=_clean_str(src.get("description")),
            enabled=_clean_bool(src.get("enabled"), True),
            priority=_clean_int(src.get("priority"), 100),
            apply_url=_clean_optional_str(src.get("apply_url")),
            doc_url=_clean_optional_str(src.get("doc_url")),
            requires_api_key=_clean_bool(src.get("requires_api_key"), False),
            credential_key_name=cred_key,
            credential_configured=masked_value is not None,
            masked_value=masked_value,
            last_check_at=_clean_datetime(src.get("last_check_at")),
            last_check_status=_clean_test_status(src.get("last_check_status")),
            last_error=_clean_optional_str(src.get("last_error")),
            updated_at=_clean_datetime(src.get("updated_at")),
        )

    def update_source(
        self,
        source_code: str,
        updates: dict[str, Any],
    ) -> MarketEventSourceConfigResponse:
        """Update source config (enabled, priority, description, etc.)."""
        self.initialize_indices()
        allowed = {"enabled", "priority", "description", "apply_url", "doc_url"}
        filtered = {k: v for k, v in updates.items() if k in allowed and v is not None}
        if not filtered:
            raise MarketEventAdminError("No valid fields to update")

        self._repo.update_source(source_code, filtered)
        return self.get_source(source_code)

    def save_credential(
        self,
        source_code: str,
        credential_key: str,
        value: str,
    ) -> MarketEventSourceConfigResponse:
        """Save or update a credential for a source."""
        if not value or not value.strip():
            raise MarketEventAdminError("Credential value must not be empty")

        src = self._repo.get_source(source_code)
        if not src:
            raise MarketEventAdminError(f"Source {source_code} not found")
        configured_key = _clean_optional_str(src.get("credential_key_name"))
        credential_key = configured_key or credential_key or "api_key"

        try:
            self._cred_store.save_credential(source_code, credential_key, value)
        except ConfigCryptoError as exc:
            raise MarketEventAdminError(str(exc)) from exc
        return self.get_source(source_code)

    def delete_credential(
        self,
        source_code: str,
        credential_key: str = "api_key",
    ) -> MarketEventSourceConfigResponse:
        """Delete a credential for a source."""
        src = self._repo.get_source(source_code)
        if not src:
            raise MarketEventAdminError(f"Source {source_code} not found")
        configured_key = _clean_optional_str(src.get("credential_key_name"))
        credential_key = configured_key or credential_key or "api_key"
        try:
            self._cred_store.delete_credential(source_code, credential_key)
            if credential_key != "api_key":
                self._cred_store.delete_credential(source_code, "api_key")
        except ConfigCryptoError as exc:
            raise MarketEventAdminError(str(exc)) from exc
        return self.get_source(source_code)

    def test_source(self, source_code: str) -> MarketEventSourceTestResponse:
        """Test a source connection through the registered provider."""
        self.initialize_indices()
        src = self._repo.get_source(source_code)
        if not src:
            raise MarketEventAdminError(f"Source {source_code} not found")

        if not src.get("enabled", True):
            status: MarketEventTestStatus = "SKIPPED"
            message = "Source is disabled"
        else:
            try:
                import asyncio

                from app.services.market_event_providers import MarketEventProviderRegistry

                provider = MarketEventProviderRegistry(self._repo, self._cred_store).get_provider(source_code)
                health = asyncio.run(provider.health_check())
            except ConfigCryptoError as exc:
                raise MarketEventAdminError(str(exc)) from exc
            except Exception as exc:
                logger.exception("Market event source test failed")
                status = "FAILED"
                message = str(exc)
            else:
                status = health.status
                message = health.message

        now = datetime.now(timezone.utc).isoformat()
        self._repo.update_source(source_code, {
            "last_check_at": now,
            "last_check_status": status,
            "last_error": None if status != "FAILED" else message,
        })

        return MarketEventSourceTestResponse(
            source_code=source_code,
            status=status,
            message=message,
        )
