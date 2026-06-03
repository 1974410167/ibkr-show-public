import json
import logging
import os
from pathlib import Path
import re
import subprocess
from typing import Any

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ModuleNotFoundError:  # pragma: no cover - optional local dependency fallback
    Redis = None
    RedisError = Exception

from app.core.config import Settings

logger = logging.getLogger(__name__)


class RedisCacheClient:
    def __init__(self, settings: Settings) -> None:
        self._ttl_seconds = settings.cache_ttl_seconds
        self._key_prefix = settings.cache_key_prefix.strip(":") or "ibkr-show"
        self._namespace_version = self._detect_namespace_version()
        self._client = (
            Redis.from_url(settings.redis_url, decode_responses=True)
            if settings.redis_url and Redis is not None
            else None
        )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def ping(self) -> bool:
        if self._client is None:
            return False
        try:
            return bool(self._client.ping())
        except RedisError:
            logger.exception("redis ping failed")
            return False

    def build_key(self, *parts: str) -> str:
        suffix = ":".join(part for part in parts if part)
        prefix = f"{self._key_prefix}:{self._namespace_version}"
        if suffix:
            return f"{prefix}:{suffix}"
        return prefix

    def get_json(self, key: str) -> dict[str, Any] | None:
        if self._client is None:
            return None

        try:
            raw_value = self._client.get(key)
        except RedisError:
            logger.exception("redis get failed for key=%s", key)
            return None

        if not raw_value:
            return None

        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            logger.warning("redis payload is not valid json for key=%s", key)
            return None

        return payload if isinstance(payload, dict) else None

    def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
        if self._client is None:
            return

        try:
            self._client.setex(key, ttl_seconds or self._ttl_seconds, json.dumps(value, ensure_ascii=True))
        except RedisError:
            logger.exception("redis set failed for key=%s", key)

    @staticmethod
    def _detect_namespace_version() -> str:
        for name in ("CACHE_VERSION", "APP_VERSION", "GIT_SHA", "GITHUB_SHA"):
            value = os.getenv(name, "").strip()
            if value:
                return RedisCacheClient._sanitize_namespace_version(value)

        repo_root = Path(__file__).resolve().parents[3]
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=repo_root,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            value = result.stdout.strip()
            if value:
                return RedisCacheClient._sanitize_namespace_version(value)
        except (OSError, subprocess.SubprocessError):
            logger.debug("git revision unavailable for cache namespace", exc_info=True)

        return "dev"

    @staticmethod
    def _sanitize_namespace_version(value: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
        return sanitized[:64] or "dev"
