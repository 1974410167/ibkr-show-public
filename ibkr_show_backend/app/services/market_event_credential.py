"""Market Event credential store with encrypted at-rest values."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.config_crypto import decrypt_config_secret, encrypt_config_secret, is_encrypted_token

MASKED_MARKER = "****"


def mask_api_key(value: str | None) -> str:
    """Mask an API key for display: show last 4 chars."""
    if not value:
        return ""
    v = value.strip()
    if len(v) <= 4:
        return MASKED_MARKER
    return f"{MASKED_MARKER}{v[-4:]}"


def is_masked_api_key(value: str | None) -> bool:
    return bool(value and MASKED_MARKER in value)


@dataclass
class MarketEventCredentialEntry:
    source_code: str
    credential_key: str = "api_key"
    value: str = ""
    masked_value: str = ""
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""
    last_used_at: str = ""


class MarketEventCredentialStore:
    """Read/write encrypted market event credentials from a JSON file on disk."""

    def __init__(self, config_file: str, encryption_key: str | None = None) -> None:
        self.config_file = Path(config_file).expanduser()
        configured_key = encryption_key if isinstance(encryption_key, str) else None
        self._encryption_key = (
            configured_key
            or os.getenv("CONFIG_ENCRYPTION_KEY")
            or os.getenv("APP_SECRET_KEY")
            or ""
        )

    def list_credentials(self) -> list[MarketEventCredentialEntry]:
        payload = self._read_payload()
        entries = []
        for item in payload.get("credentials", []):
            if isinstance(item, dict):
                entries.append(self._entry_from_dict(item))
        return entries

    def get_credential(self, source_code: str) -> MarketEventCredentialEntry | None:
        for entry in self.list_credentials():
            if entry.source_code == source_code:
                return entry
        return None

    def get_decrypted_value(self, source_code: str, credential_key: str = "api_key") -> str | None:
        """Get the raw credential value for server-side provider use."""
        entry = self.get_credential(source_code)
        if not entry:
            return None
        if entry.credential_key != credential_key:
            return None
        if not entry.value:
            return None
        return decrypt_config_secret(entry.value, self._encryption_key) or None

    def save_credential(
        self,
        source_code: str,
        credential_key: str,
        value: str,
    ) -> MarketEventCredentialEntry:
        """Save or update a credential. Returns the saved entry."""
        now = datetime.now(timezone.utc).isoformat()
        entries = self.list_credentials()
        found = False
        encrypted_value = encrypt_config_secret(value, self._encryption_key)
        for entry in entries:
            if entry.source_code == source_code and entry.credential_key == credential_key:
                entry.value = encrypted_value
                entry.masked_value = mask_api_key(value)
                entry.updated_at = now
                found = True
                break

        if not found:
            entry = MarketEventCredentialEntry(
                source_code=source_code,
                credential_key=credential_key,
                value=encrypted_value,
                masked_value=mask_api_key(value),
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            entries.append(entry)

        self._save_entries(entries)
        return entry

    def delete_credential(self, source_code: str, credential_key: str = "api_key") -> bool:
        """Delete a credential. Returns True if found and deleted."""
        entries = self.list_credentials()
        new_entries = [
            e for e in entries
            if not (e.source_code == source_code and e.credential_key == credential_key)
        ]
        if len(new_entries) == len(entries):
            return False
        self._save_entries(new_entries)
        return True

    def _read_payload(self) -> dict[str, Any]:
        if not self.config_file.exists():
            return {"credentials": []}
        try:
            with self.config_file.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except json.JSONDecodeError:
            return {"credentials": []}
        if not isinstance(payload, dict):
            return {"credentials": []}
        return payload

    def _save_entries(self, entries: list[MarketEventCredentialEntry]) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            if entry.value and not is_encrypted_token(entry.value):
                entry.value = encrypt_config_secret(entry.value, self._encryption_key)
        payload = {"credentials": [asdict(e) for e in entries]}
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{self.config_file.name}.",
            suffix=".tmp",
            dir=self.config_file.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(temp_path, self.config_file)
            try:
                os.chmod(self.config_file, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def _entry_from_dict(self, item: dict[str, Any]) -> MarketEventCredentialEntry:
        return MarketEventCredentialEntry(
            source_code=str(item.get("source_code", "")),
            credential_key=str(item.get("credential_key", "api_key")),
            value=str(item.get("value", "")),
            masked_value=str(item.get("masked_value", "")),
            enabled=bool(item.get("enabled", True)),
            created_at=str(item.get("created_at", "")),
            updated_at=str(item.get("updated_at", "")),
            last_used_at=str(item.get("last_used_at", "")),
        )
