import json
import logging
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
        self._client = (
            Redis.from_url(settings.redis_url, decode_responses=True)
            if settings.redis_url and Redis is not None
            else None
        )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def build_key(self, *parts: str) -> str:
        suffix = ":".join(part for part in parts if part)
        if suffix:
            return f"{self._key_prefix}:{suffix}"
        return self._key_prefix

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
