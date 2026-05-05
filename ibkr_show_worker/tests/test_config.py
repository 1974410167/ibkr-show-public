from worker.core.config import get_settings


def test_flex_polling_defaults_wait_long_enough_for_slow_statement_generation(monkeypatch) -> None:
    monkeypatch.delenv("FLEX_POLL_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("FLEX_MAX_POLL_RETRIES", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.flex_poll_interval_seconds == 10
    assert settings.flex_max_poll_retries == 60
    assert settings.flex_poll_interval_seconds * settings.flex_max_poll_retries >= 600

    get_settings.cache_clear()
