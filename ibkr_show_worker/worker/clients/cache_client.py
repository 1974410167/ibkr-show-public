import logging

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ModuleNotFoundError:  # pragma: no cover - optional local dependency fallback
    Redis = None
    RedisError = Exception

from worker.core.config import Settings

logger = logging.getLogger(__name__)


class RedisCacheInvalidator:
    def __init__(self, settings: Settings) -> None:
        self._key_prefix = settings.cache_key_prefix.strip(":") or "ibkr-show"
        self._client = (
            Redis.from_url(settings.redis_url, decode_responses=True)
            if settings.redis_url and Redis is not None
            else None
        )

    def clear_all(self) -> int:
        if self._client is None:
            return 0

        deleted = 0
        try:
            cursor = 0
            pattern = f"{self._key_prefix}:*"
            while True:
                cursor, keys = self._client.scan(cursor=cursor, match=pattern, count=200)
                if keys:
                    deleted += int(self._client.delete(*keys))
                if cursor == 0:
                    break
        except RedisError:
            logger.exception("redis cache invalidation failed for prefix=%s", self._key_prefix)
            return 0

        return deleted
