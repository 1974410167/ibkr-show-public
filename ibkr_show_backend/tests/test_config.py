from app.core.config import get_settings


def test_cache_ttl_defaults_to_one_hour(monkeypatch) -> None:
    monkeypatch.delenv("CACHE_TTL_SECONDS", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.cache_ttl_seconds == 3600

    get_settings.cache_clear()


def test_agent_observability_indices_default_to_v2(monkeypatch) -> None:
    monkeypatch.delenv("ES_AGENT_RUN_TRACE_INDEX", raising=False)
    monkeypatch.delenv("ES_AGENT_REPLAY_INDEX", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.es_agent_run_trace_index == "ibkr_agent_run_traces_v2"
    assert settings.es_agent_replay_index == "ibkr_agent_replay_snapshots_v2"

    get_settings.cache_clear()
