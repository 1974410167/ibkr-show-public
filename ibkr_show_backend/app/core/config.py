from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    app_host: str
    app_port: int
    cors_allow_origins: str
    cors_allow_origin_regex: str
    auth_username: str
    auth_password: str
    auth_session_secret: str
    auth_session_max_age_seconds: int
    es_host: str
    es_username: str
    es_password: str
    es_verify_certs: bool
    es_account_index: str
    es_position_index: str
    es_trade_index: str
    es_cash_flow_index: str
    es_price_history_index: str
    es_trade_review_index: str
    es_trade_decision_index: str
    es_daily_position_review_index: str
    es_agent_task_index: str
    es_agent_prompt_index: str
    es_agent_run_trace_index: str
    es_agent_replay_index: str
    es_agent_eval_case_index: str
    es_agent_eval_run_index: str
    es_agent_feedback_index: str
    es_agent_regression_profile_index: str
    es_agent_regression_gate_report_index: str
    es_risk_assessment_index: str
    es_copilot_session_index: str
    es_copilot_message_index: str
    es_copilot_run_index: str
    es_copilot_memory_index: str
    es_copilot_event_index: str
    es_copilot_tool_probe_index: str
    es_copilot_tool_call_metrics_index: str
    es_copilot_llm_call_metrics_index: str
    es_structured_output_metrics_index: str
    es_llm_call_metrics_index: str
    account_copilot_run_timeout_seconds: int
    account_copilot_max_react_rounds: int
    account_copilot_max_event_payload_chars: int
    account_copilot_demo_mode: bool
    longbridge_enable: bool
    longbridge_openapi_oauth_client_id: str
    longbridge_openapi_oauth_file: str
    longbridge_openapi_oauth_scope: str
    llm_enable: bool
    llm_default_provider_name: str
    llm_default_base_url: str
    llm_default_api_key: str
    llm_default_model: str
    llm_config_file: str
    email_config_file: str
    ibkr_flex_config_file: str
    ibkr_flex_base_url: str
    ibkr_flex_user_agent: str
    ibkr_flex_poll_interval_seconds: int
    ibkr_flex_max_poll_retries: int
    redis_url: str
    cache_ttl_seconds: int
    cache_key_prefix: str
    daily_review_internal_token: str
    admin_auth_config_file: str


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "ibkr_show_backend"),
        app_env=os.getenv("APP_ENV", "dev"),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        cors_allow_origins=os.getenv(
            "CORS_ALLOW_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ),
        cors_allow_origin_regex=os.getenv("CORS_ALLOW_ORIGIN_REGEX", r"https?://.*"),
        auth_username=os.getenv("AUTH_USERNAME", "admin"),
        auth_password=os.getenv("AUTH_PASSWORD", "change-me"),
        auth_session_secret=os.getenv("AUTH_SESSION_SECRET", "change-me-session-secret"),
        auth_session_max_age_seconds=int(os.getenv("AUTH_SESSION_MAX_AGE_SECONDS", "604800")),
        es_host=os.getenv("ES_HOST", "http://localhost:9200"),
        es_username=os.getenv("ES_USERNAME", ""),
        es_password=os.getenv("ES_PASSWORD", ""),
        es_verify_certs=_read_bool("ES_VERIFY_CERTS", False),
        es_account_index=os.getenv("ES_ACCOUNT_INDEX", "ibkr_account_daily_snapshot_v1"),
        es_position_index=os.getenv("ES_POSITION_INDEX", "ibkr_position_daily_snapshot_v1"),
        es_trade_index=os.getenv("ES_TRADE_INDEX", "ibkr_trade_records_v1"),
        es_cash_flow_index=os.getenv("ES_CASH_FLOW_INDEX", "ibkr_cash_flow_records_v1"),
        es_price_history_index=os.getenv("ES_PRICE_HISTORY_INDEX", "ibkr_symbol_price_history_v1"),
        es_trade_review_index=os.getenv("ES_TRADE_REVIEW_INDEX", "ibkr_trade_reviews_v1"),
        es_trade_decision_index=os.getenv("ES_TRADE_DECISION_INDEX", "ibkr_trade_decisions_v1"),
        es_daily_position_review_index=os.getenv("ES_DAILY_POSITION_REVIEW_INDEX", "ibkr_daily_position_reviews_v1"),
        es_agent_task_index=os.getenv("ES_AGENT_TASK_INDEX", "ibkr_agent_tasks_v1"),
        es_agent_prompt_index=os.getenv("ES_AGENT_PROMPT_INDEX", "ibkr_agent_prompts"),
        es_agent_run_trace_index=os.getenv("ES_AGENT_RUN_TRACE_INDEX", "ibkr_agent_run_traces_v2"),
        es_agent_replay_index=os.getenv("ES_AGENT_REPLAY_INDEX", "ibkr_agent_replay_snapshots_v2"),
        es_agent_eval_case_index=os.getenv("ES_AGENT_EVAL_CASE_INDEX", "ibkr_agent_eval_cases"),
        es_agent_eval_run_index=os.getenv("ES_AGENT_EVAL_RUN_INDEX", "ibkr_agent_eval_runs"),
        es_agent_feedback_index=os.getenv("ES_AGENT_FEEDBACK_INDEX", "ibkr_agent_feedback"),
        es_agent_regression_profile_index=os.getenv("ES_AGENT_REGRESSION_PROFILE_INDEX", "ibkr_agent_regression_profiles"),
        es_agent_regression_gate_report_index=os.getenv("ES_AGENT_REGRESSION_GATE_REPORT_INDEX", "ibkr_agent_regression_gate_reports"),
        es_risk_assessment_index=os.getenv("ES_RISK_ASSESSMENT_INDEX", "ibkr_risk_assessments_v1"),
        es_copilot_session_index=os.getenv("ES_COPILOT_SESSION_INDEX", "ibkr_copilot_sessions_v1"),
        es_copilot_message_index=os.getenv("ES_COPILOT_MESSAGE_INDEX", "ibkr_copilot_messages_v1"),
        es_copilot_run_index=os.getenv("ES_COPILOT_RUN_INDEX", "ibkr_copilot_runs_v1"),
        es_copilot_memory_index=os.getenv("ES_COPILOT_MEMORY_INDEX", "ibkr_copilot_memories_v1"),
        es_copilot_event_index=os.getenv("ES_COPILOT_EVENT_INDEX", "ibkr_copilot_events_v1"),
        es_copilot_tool_probe_index=os.getenv("ES_COPILOT_TOOL_PROBE_INDEX", "ibkr_copilot_tool_probe_results_v1"),
        es_copilot_tool_call_metrics_index=os.getenv("ES_COPILOT_TOOL_CALL_METRICS_INDEX", "ibkr_copilot_tool_call_metrics_v1"),
        es_copilot_llm_call_metrics_index=os.getenv("ES_COPILOT_LLM_CALL_METRICS_INDEX", "ibkr_copilot_llm_call_metrics_v1"),
        es_structured_output_metrics_index=os.getenv("ES_STRUCTURED_OUTPUT_METRICS_INDEX", "ibkr_structured_output_metrics_v1"),
        es_llm_call_metrics_index=os.getenv("ES_LLM_CALL_METRICS_INDEX", "ibkr_llm_call_metrics"),
        account_copilot_run_timeout_seconds=int(os.getenv("ACCOUNT_COPILOT_RUN_TIMEOUT_SECONDS", "180")),
        account_copilot_max_react_rounds=int(os.getenv("ACCOUNT_COPILOT_MAX_REACT_ROUNDS", "8")),
        account_copilot_max_event_payload_chars=int(os.getenv("ACCOUNT_COPILOT_MAX_EVENT_PAYLOAD_CHARS", "6000")),
        account_copilot_demo_mode=_read_bool("ACCOUNT_COPILOT_DEMO_MODE", False),
        longbridge_enable=_read_bool("LONGBRIDGE_ENABLE", True),
        longbridge_openapi_oauth_client_id=os.getenv("LONGBRIDGE_OPENAPI_OAUTH_CLIENT_ID", ""),
        longbridge_openapi_oauth_file=os.getenv(
            "LONGBRIDGE_OPENAPI_OAUTH_FILE",
            str(BASE_DIR / "data" / "config" / "longbridge_openapi_oauth.json"),
        ),
        longbridge_openapi_oauth_scope=os.getenv("LONGBRIDGE_OPENAPI_OAUTH_SCOPE", ""),
        llm_enable=_read_bool("LLM_ENABLE", True),
        llm_default_provider_name=os.getenv("LLM_DEFAULT_PROVIDER_NAME", ""),
        llm_default_base_url=os.getenv("LLM_DEFAULT_BASE_URL", ""),
        llm_default_api_key=os.getenv("LLM_DEFAULT_API_KEY", ""),
        llm_default_model=os.getenv("LLM_DEFAULT_MODEL", ""),
        llm_config_file=os.getenv("LLM_CONFIG_FILE", str(BASE_DIR / "data" / "config" / "llm_providers.json")),
        email_config_file=os.getenv("EMAIL_CONFIG_FILE") or str(BASE_DIR / "data" / "config" / "email.json"),
        ibkr_flex_config_file=os.getenv(
            "IBKR_FLEX_CONFIG_FILE",
            str(BASE_DIR / "data" / "config" / "ibkr_flex.json"),
        ),
        ibkr_flex_base_url=os.getenv(
            "FLEX_BASE_URL",
            "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService",
        ),
        ibkr_flex_user_agent=os.getenv("FLEX_USER_AGENT", "ibkr-show-backend/0.1"),
        ibkr_flex_poll_interval_seconds=int(os.getenv("FLEX_POLL_INTERVAL_SECONDS", "10")),
        ibkr_flex_max_poll_retries=int(os.getenv("FLEX_MAX_POLL_RETRIES", "60")),
        redis_url=os.getenv("REDIS_URL", ""),
        cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "3600")),
        cache_key_prefix=os.getenv("CACHE_KEY_PREFIX", "ibkr-show"),
        daily_review_internal_token=os.getenv("DAILY_REVIEW_INTERNAL_TOKEN", ""),
        admin_auth_config_file=os.getenv(
            "ADMIN_AUTH_CONFIG_FILE",
            str(BASE_DIR / "data" / "config" / "admin_auth.json"),
        ),
    )
