from types import SimpleNamespace
from unittest.mock import patch

from app.clients.cache_client import RedisCacheClient


def _settings(prefix: str = "ibkr-show") -> SimpleNamespace:
    return SimpleNamespace(
        cache_ttl_seconds=86400,
        cache_key_prefix=prefix,
        redis_url="",
    )


def test_cache_key_includes_explicit_cache_version() -> None:
    with patch.dict("os.environ", {"CACHE_VERSION": "positions-v3"}, clear=False):
        client = RedisCacheClient(_settings())

    assert client.build_key("positions", "page=1") == "ibkr-show:positions-v3:positions:page=1"


def test_cache_key_sanitizes_namespace_version() -> None:
    with patch.dict("os.environ", {"CACHE_VERSION": "release/2026 06 01"}, clear=False):
        client = RedisCacheClient(_settings("custom"))

    assert client.build_key("account-overview") == "custom:release-2026-06-01:account-overview"


def test_cache_key_uses_git_revision_when_no_explicit_version() -> None:
    completed = SimpleNamespace(stdout="abc1234\n")
    with (
        patch.dict("os.environ", {"CACHE_VERSION": "", "APP_VERSION": "", "GIT_SHA": "", "GITHUB_SHA": ""}, clear=False),
        patch("app.clients.cache_client.subprocess.run", return_value=completed),
    ):
        client = RedisCacheClient(_settings())

    assert client.build_key("equity-curve") == "ibkr-show:abc1234:equity-curve"
