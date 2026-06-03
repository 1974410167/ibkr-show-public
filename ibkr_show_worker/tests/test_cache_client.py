from types import SimpleNamespace

from worker.clients import cache_client
from worker.clients.cache_client import RedisCacheInvalidator


class FakeRedis:
    def __init__(self) -> None:
        self.scan_calls: list[dict] = []
        self.delete_calls: list[tuple[str, ...]] = []

    def scan(self, cursor: int, match: str, count: int):
        self.scan_calls.append({"cursor": cursor, "match": match, "count": count})
        if cursor == 0:
            return 1, ["ibkr-show:old:positions", "ibkr-show:new:account-overview"]
        return 0, ["ibkr-show:new:equity-curve"]

    def delete(self, *keys: str) -> int:
        self.delete_calls.append(keys)
        return len(keys)


def test_clear_all_deletes_all_cache_namespaces_for_prefix(monkeypatch) -> None:
    fake_redis = FakeRedis()
    monkeypatch.setattr(cache_client, "Redis", SimpleNamespace(from_url=lambda redis_url, decode_responses: fake_redis))

    settings = SimpleNamespace(redis_url="redis://localhost:6379/0", cache_key_prefix="ibkr-show")
    deleted = RedisCacheInvalidator(settings).clear_all()

    assert deleted == 3
    assert fake_redis.scan_calls == [
        {"cursor": 0, "match": "ibkr-show:*", "count": 200},
        {"cursor": 1, "match": "ibkr-show:*", "count": 200},
    ]
    assert fake_redis.delete_calls == [
        ("ibkr-show:old:positions", "ibkr-show:new:account-overview"),
        ("ibkr-show:new:equity-curve",),
    ]
