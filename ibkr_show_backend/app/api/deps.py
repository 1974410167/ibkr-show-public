import logging
from functools import lru_cache
from pathlib import Path

from fastapi import Cookie, Depends, HTTPException, status

from app.clients.es_client import ElasticsearchClient
from app.clients.cache_client import RedisCacheClient
from app.agents.account_copilot.longbridge_tools import AccountCopilotLongbridgeToolService
from app.agents.account_copilot.skill_registry import AccountCopilotSkillRegistry, build_default_skill_registry
from app.agents.account_copilot.subagent_registry import AccountCopilotSubAgentRegistry, build_default_subagent_registry
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry, build_default_tool_registry
from app.agents.eval_judge import AgentEvalJudgeService
from app.core.auth import SESSION_COOKIE_NAME, AuthSession, verify_session_token
from app.core.config import Settings, get_settings
from app.services.account_service import AccountService
from app.services.account_copilot import (
    AccountCopilotEventBus,
    AccountCopilotEventRepository,
    AccountCopilotIBKRToolService,
    AccountCopilotMemoryRepository,
    AccountCopilotMemoryService,
    AccountCopilotDemoService,
    AccountCopilotMessageService,
    AccountCopilotRepository,
    AccountCopilotRunService,
    AccountCopilotSessionService,
    AccountCopilotSkillService,
    AccountCopilotSubAgentService,
    AccountCopilotMonitoringRepository,
    AccountCopilotMonitoringService,
    AccountCopilotToolReliabilityRepository,
    AccountCopilotToolReliabilityService,
)
from app.services.account_copilot.approval_service import AccountCopilotApprovalService
from app.services.agent_task_repository import AgentTaskRepository
from app.services.agent_run_trace_repository import AgentRunTraceRepository
from app.services.agent_run_trace_service import AgentRunTraceService
from app.services.agent_replay_repository import AgentReplayRepository
from app.services.agent_replay_service import AgentReplayService
from app.services.agent_eval_repository import BadCaseFeedbackRepository, EvalCaseRepository, EvalRunRepository, RegressionGateReportRepository, RegressionProfileRepository
from app.services.agent_eval_service import AgentEvalService
from app.services.eval_simulation_repository import SyntheticSimulationRepository
from app.services.eval_simulation_executors import RealSimulationAgentExecutor
from app.services.eval_simulation_service import SyntheticSimulationService
from app.services.eval_failure_mining_repository import SyntheticFailureMiningRepository
from app.services.eval_failure_mining_service import SyntheticFailureMiningService
from app.services.eval_failure_to_case_service import FailureToEvalCaseService
from app.services.eval_baseline_health_repository import BaselineHealthReportRepository
from app.services.eval_baseline_health_service import BaselineHealthReportService
from app.services.eval_judge_calibration_repository import JudgeCalibrationRepository
from app.services.eval_judge_calibration_service import JudgeCalibrationService
from app.services.agent_regression_profile_service import RegressionProfileService
from app.services.agent_change_impact_service import AgentChangeImpactService
from app.services.agent_regression_gate_service import AgentRegressionGateService
from app.services.admin_ibkr_service import AdminIBKRService
from app.services.admin_prompt_repository import AdminPromptRepository
from app.services.admin_prompt_service import AdminPromptService
from app.services.cash_flow_service import CashFlowService
from app.services.chart_service import ChartService
from app.services.daily_position_review_agent import DailyPositionReviewAgent
from app.services.daily_position_review_repository import DailyPositionReviewRepository
from app.services.daily_position_review_service import DailyPositionReviewService
from app.services.daily_review_related_asset_service import DailyReviewRelatedAssetService
from app.services.daily_review_macro_evidence_agent import DailyReviewMacroEvidenceAgent
from app.services.daily_review_symbol_evidence_agent import DailyReviewSymbolEvidenceAgent
from app.services.daily_account_snapshot_service import DailyAccountSnapshotService
from app.services.dividend_service import DividendService
from app.services.email_service import EmailService
from app.services.investment_policy_repository import InvestmentPolicyRepository
from app.services.investment_policy_service import InvestmentPolicyService
from app.services.llm_service import LLMService
from app.services.llm_call_metrics_repository import LLMCallMetricsRepository
from app.services.llm_call_metrics_service import LLMCallMetricsService
from app.services.longbridge_service import LongbridgeExternalDataClient
from app.services.longbridge_openapi_oauth import LongbridgeOpenAPIOAuthService
from app.services.longbridge_oauth_token_service import LongbridgeOAuthTokenService
from app.services.trade_decision_agent import TradeDecisionAgent
from app.services.trade_decision_evidence import TradeDecisionEvidenceBuilder
from app.services.trade_decision_metrics import TradeDecisionMetricsCalculator
from app.services.trade_decision_outcome_replay import TradeDecisionOutcomePriceProvider, TradeDecisionOutcomeReplayService
from app.services.trade_decision_repository import TradeDecisionRepository
from app.services.risk_assessment_agent import RiskAssessmentAgent
from app.services.risk_assessment_repository import RiskAssessmentRepository
from app.services.position_service import PositionService
from app.services.symbol_analysis_service import SymbolAnalysisService
from app.services.symbol_suggest_service import SymbolSuggestService
from app.services.trade_review_agent import TradeReviewAgent
from app.services.trade_review_evidence import TradeReviewEvidenceBuilder
from app.services.trade_review_repository import TradeReviewRepository
from app.services.trade_review_scoring import TradeReviewMetricsCalculator
from app.services.trade_service import TradeService
from app.services.public_market_evidence_builder import PublicMarketEvidenceBuilder
from app.services.public_market_research_subagent import PublicMarketResearchSubAgent

logger = logging.getLogger(__name__)


@lru_cache
def get_es_client() -> ElasticsearchClient:
    return ElasticsearchClient(get_settings())


@lru_cache
def get_cache_client() -> RedisCacheClient:
    return RedisCacheClient(get_settings())


def get_account_service() -> AccountService:
    return AccountService(get_es_client(), get_settings(), get_cache_client())


def get_chart_service() -> ChartService:
    return ChartService(get_es_client(), get_settings(), get_cache_client())


def get_position_service() -> PositionService:
    return PositionService(get_es_client(), get_settings(), get_cache_client())


def get_trade_service() -> TradeService:
    return TradeService(get_es_client(), get_settings())


def get_cash_flow_service() -> CashFlowService:
    return CashFlowService(get_es_client(), get_settings())


def get_dividend_service() -> DividendService:
    return DividendService(get_es_client(), get_settings())


def get_longbridge_external_data_client() -> LongbridgeExternalDataClient:
    settings = get_settings()
    return LongbridgeExternalDataClient(settings, get_longbridge_openapi_oauth_service(settings))


def get_llm_call_metrics_repository() -> LLMCallMetricsRepository:
    return LLMCallMetricsRepository(get_es_client(), get_settings())


def get_llm_call_metrics_service() -> LLMCallMetricsService:
    return LLMCallMetricsService(get_llm_call_metrics_repository())


def get_llm_service() -> LLMService:
    return LLMService(get_settings(), metrics_service=get_llm_call_metrics_service())


def get_admin_ibkr_service() -> AdminIBKRService:
    return AdminIBKRService(get_settings())


def get_admin_prompt_repository() -> AdminPromptRepository:
    return AdminPromptRepository(get_es_client(), get_settings())


def get_admin_prompt_service(
    repository: AdminPromptRepository = Depends(get_admin_prompt_repository),
) -> AdminPromptService:
    return AdminPromptService(repository)


def get_investment_policy_repository() -> InvestmentPolicyRepository:
    return InvestmentPolicyRepository(get_es_client(), get_settings())


def get_investment_policy_service(
    repository: InvestmentPolicyRepository = Depends(get_investment_policy_repository),
) -> InvestmentPolicyService:
    return InvestmentPolicyService(repository)


def get_email_service() -> EmailService:
    return EmailService(get_settings())


def get_longbridge_openapi_oauth_service(settings: Settings | None = None) -> LongbridgeOpenAPIOAuthService:
    return LongbridgeOpenAPIOAuthService(settings or get_settings())


def get_longbridge_oauth_token_service() -> LongbridgeOAuthTokenService:
    settings = get_settings()
    return LongbridgeOAuthTokenService(
        settings=settings,
        openapi_oauth_service=get_longbridge_openapi_oauth_service(settings),
    )


def get_agent_task_repository() -> AgentTaskRepository:
    return AgentTaskRepository(get_es_client(), get_settings())


def get_agent_run_trace_repository() -> AgentRunTraceRepository:
    return AgentRunTraceRepository(get_es_client(), get_settings())


def get_agent_run_trace_service() -> AgentRunTraceService:
    return AgentRunTraceService(get_agent_run_trace_repository())


def get_agent_replay_repository() -> AgentReplayRepository:
    return AgentReplayRepository(get_es_client(), get_settings())


def get_agent_replay_service() -> AgentReplayService:
    return AgentReplayService(get_agent_replay_repository())


def get_agent_eval_case_repository() -> EvalCaseRepository:
    return EvalCaseRepository(get_es_client(), get_settings())


def get_agent_eval_run_repository() -> EvalRunRepository:
    return EvalRunRepository(get_es_client(), get_settings())


def get_agent_feedback_repository() -> BadCaseFeedbackRepository:
    return BadCaseFeedbackRepository(get_es_client(), get_settings())


def get_agent_eval_service() -> AgentEvalService:
    return AgentEvalService(
        get_agent_eval_case_repository(),
        get_agent_eval_run_repository(),
        replay_service=get_agent_replay_service(),
        llm_client=get_llm_service() if get_settings().llm_enable else None,
        feedback_repository=get_agent_feedback_repository(),
        llm_call_service=get_llm_call_metrics_service(),
        run_trace_repository=get_agent_run_trace_repository(),
    )


def get_eval_simulation_repository() -> SyntheticSimulationRepository:
    return SyntheticSimulationRepository(get_es_client(), get_settings())


def get_eval_simulation_service() -> SyntheticSimulationService:
    return SyntheticSimulationService(
        get_eval_simulation_repository(),
        real_executor=RealSimulationAgentExecutor(
            trade_decision_agent=get_trade_decision_agent(),
            daily_position_review_agent=get_daily_position_review_agent(),
            daily_position_review_service=get_daily_position_review_service(),
            trade_review_agent=get_trade_review_agent(),
            allow_live_account_copilot=False,
        ),
    )


def get_eval_failure_mining_repository() -> SyntheticFailureMiningRepository:
    return SyntheticFailureMiningRepository(get_es_client(), get_settings())


def get_eval_failure_mining_service() -> SyntheticFailureMiningService:
    return SyntheticFailureMiningService(
        failure_repository=get_eval_failure_mining_repository(),
        simulation_repository=get_eval_simulation_repository(),
        judge_service=AgentEvalJudgeService(llm_client=get_llm_service()) if get_settings().llm_enable else None,
    )


def get_failure_to_eval_case_service() -> FailureToEvalCaseService:
    return FailureToEvalCaseService(
        failure_repository=get_eval_failure_mining_repository(),
        simulation_repository=get_eval_simulation_repository(),
        case_repository=get_agent_eval_case_repository(),
    )


def get_baseline_health_report_repository() -> BaselineHealthReportRepository:
    return BaselineHealthReportRepository(get_es_client(), get_settings())


def get_baseline_health_report_service() -> BaselineHealthReportService:
    return BaselineHealthReportService(
        report_repository=get_baseline_health_report_repository(),
        simulation_repository=get_eval_simulation_repository(),
        failure_repository=get_eval_failure_mining_repository(),
        case_repository=get_agent_eval_case_repository(),
        agent_eval_service=get_agent_eval_service(),
    )


def get_judge_calibration_repository() -> JudgeCalibrationRepository:
    return JudgeCalibrationRepository(get_es_client(), get_settings())


def get_judge_calibration_service() -> JudgeCalibrationService:
    return JudgeCalibrationService(
        calibration_repository=get_judge_calibration_repository(),
        failure_repository=get_eval_failure_mining_repository(),
        simulation_repository=get_eval_simulation_repository(),
        baseline_report_repository=get_baseline_health_report_repository(),
        case_repository=get_agent_eval_case_repository(),
    )


def get_agent_regression_profile_repository() -> RegressionProfileRepository:
    return RegressionProfileRepository(get_es_client(), get_settings())


def get_agent_regression_profile_service() -> RegressionProfileService:
    return RegressionProfileService(get_agent_regression_profile_repository())


def get_agent_change_impact_service() -> AgentChangeImpactService:
    repo_root = str(Path(__file__).resolve().parents[2])
    return AgentChangeImpactService(get_agent_regression_profile_service(), repo_root=repo_root)


def get_agent_regression_gate_report_repository() -> RegressionGateReportRepository:
    return RegressionGateReportRepository(get_es_client(), get_settings())


def get_agent_regression_gate_service() -> AgentRegressionGateService:
    return AgentRegressionGateService(
        get_agent_change_impact_service(),
        get_agent_eval_service(),
        report_repository=get_agent_regression_gate_report_repository(),
    )


def get_account_copilot_repository() -> AccountCopilotRepository:
    return AccountCopilotRepository(get_es_client(), get_settings())


def get_account_copilot_session_service(
    repository: AccountCopilotRepository = Depends(get_account_copilot_repository),
) -> AccountCopilotSessionService:
    return AccountCopilotSessionService(repository)


def get_account_copilot_message_service(
    repository: AccountCopilotRepository = Depends(get_account_copilot_repository),
) -> AccountCopilotMessageService:
    return AccountCopilotMessageService(repository)


def get_account_copilot_run_service(
    repository: AccountCopilotRepository = Depends(get_account_copilot_repository),
) -> AccountCopilotRunService:
    return AccountCopilotRunService(repository)


def get_account_copilot_memory_repository() -> AccountCopilotMemoryRepository:
    return AccountCopilotMemoryRepository(get_es_client(), get_settings())


def get_account_copilot_memory_service(
    repository: AccountCopilotRepository = Depends(get_account_copilot_repository),
    memory_repository: AccountCopilotMemoryRepository = Depends(get_account_copilot_memory_repository),
    llm_service: LLMService = Depends(get_llm_service),
) -> AccountCopilotMemoryService:
    return AccountCopilotMemoryService(repository, memory_repository, llm_service)


def get_account_copilot_event_repository() -> AccountCopilotEventRepository:
    return AccountCopilotEventRepository(get_es_client(), get_settings())


@lru_cache
def _get_account_copilot_event_bus_cached() -> AccountCopilotEventBus:
    settings = get_settings()
    return AccountCopilotEventBus(
        AccountCopilotEventRepository(get_es_client(), settings),
        max_payload_chars=settings.account_copilot_max_event_payload_chars,
    )


def get_account_copilot_event_bus() -> AccountCopilotEventBus:
    return _get_account_copilot_event_bus_cached()


def get_account_copilot_demo_service(
    repository: AccountCopilotRepository = Depends(get_account_copilot_repository),
    memory_repository: AccountCopilotMemoryRepository = Depends(get_account_copilot_memory_repository),
    event_bus: AccountCopilotEventBus = Depends(get_account_copilot_event_bus),
) -> AccountCopilotDemoService:
    return AccountCopilotDemoService(repository, memory_repository, event_bus)


def get_account_copilot_ibkr_tool_service() -> AccountCopilotIBKRToolService:
    return AccountCopilotIBKRToolService(
        get_es_client(),
        get_settings(),
        get_account_service(),
        get_chart_service(),
        get_daily_position_review_service(),
        get_risk_assessment_account_facts_builder(),
    )


def get_account_copilot_longbridge_tool_service() -> AccountCopilotLongbridgeToolService:
    return AccountCopilotLongbridgeToolService(_get_optional_mcp_adapter())


def get_account_copilot_tool_registry(
    ibkr_tool_service: AccountCopilotIBKRToolService = Depends(get_account_copilot_ibkr_tool_service),
    longbridge_tool_service: AccountCopilotLongbridgeToolService = Depends(get_account_copilot_longbridge_tool_service),
) -> AccountCopilotToolRegistry:
    return build_default_tool_registry(ibkr_tool_service, longbridge_tool_service)


def get_account_copilot_skill_service() -> AccountCopilotSkillService:
    return AccountCopilotSkillService(
        trade_decision_agent=get_trade_decision_agent(),
        trade_review_agent=get_trade_review_agent(),
        daily_position_review_agent=get_daily_position_review_agent(),
        risk_assessment_agent=get_risk_assessment_agent(),
    )


def get_account_copilot_skill_registry(
    skill_service: AccountCopilotSkillService = Depends(get_account_copilot_skill_service),
) -> AccountCopilotSkillRegistry:
    return build_default_skill_registry(skill_service)


def get_public_market_evidence_builder(
    longbridge_tool_service: AccountCopilotLongbridgeToolService = Depends(get_account_copilot_longbridge_tool_service),
) -> PublicMarketEvidenceBuilder:
    return PublicMarketEvidenceBuilder(longbridge_tool_service)


def get_public_market_research_subagent(
    evidence_builder: PublicMarketEvidenceBuilder = Depends(get_public_market_evidence_builder),
    llm_service: LLMService = Depends(get_llm_service),
) -> PublicMarketResearchSubAgent:
    return PublicMarketResearchSubAgent(evidence_builder, llm_service)


def get_account_copilot_subagent_service() -> AccountCopilotSubAgentService:
    return AccountCopilotSubAgentService()


def get_account_copilot_subagent_registry(
    public_market_research_subagent: PublicMarketResearchSubAgent = Depends(get_public_market_research_subagent),
) -> AccountCopilotSubAgentRegistry:
    return build_default_subagent_registry(public_market_research_subagent)


def get_account_copilot_tool_reliability_repository() -> AccountCopilotToolReliabilityRepository:
    return AccountCopilotToolReliabilityRepository(get_es_client(), get_settings())


def get_account_copilot_tool_reliability_service(
    repository: AccountCopilotToolReliabilityRepository = Depends(get_account_copilot_tool_reliability_repository),
    tool_registry: AccountCopilotToolRegistry = Depends(get_account_copilot_tool_registry),
    skill_registry: AccountCopilotSkillRegistry = Depends(get_account_copilot_skill_registry),
) -> AccountCopilotToolReliabilityService:
    return AccountCopilotToolReliabilityService(
        repository=repository,
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        longbridge_adapter=_get_optional_mcp_adapter(),
    )


def get_account_copilot_monitoring_repository() -> AccountCopilotMonitoringRepository:
    return AccountCopilotMonitoringRepository(get_es_client(), get_settings())


def get_account_copilot_monitoring_service(
    repository: AccountCopilotMonitoringRepository = Depends(get_account_copilot_monitoring_repository),
) -> AccountCopilotMonitoringService:
    return AccountCopilotMonitoringService(repository)


def get_account_copilot_approval_service(
    run_service: AccountCopilotRunService = Depends(get_account_copilot_run_service),
    message_service: AccountCopilotMessageService = Depends(get_account_copilot_message_service),
    session_service: AccountCopilotSessionService = Depends(get_account_copilot_session_service),
    skill_registry: AccountCopilotSkillRegistry = Depends(get_account_copilot_skill_registry),
    skill_service: AccountCopilotSkillService = Depends(get_account_copilot_skill_service),
    llm_service: LLMService = Depends(get_llm_service),
    tool_registry: AccountCopilotToolRegistry = Depends(get_account_copilot_tool_registry),
    event_bus: AccountCopilotEventBus = Depends(get_account_copilot_event_bus),
    monitoring_service: AccountCopilotMonitoringService = Depends(get_account_copilot_monitoring_service),
) -> AccountCopilotApprovalService:
    return AccountCopilotApprovalService(
        run_service=run_service,
        message_service=message_service,
        session_service=session_service,
        skill_registry=skill_registry,
        skill_service=skill_service,
        llm_service=llm_service,
        tool_registry=tool_registry,
        event_bus=event_bus,
        monitoring_service=monitoring_service,
    )


def get_symbol_analysis_service() -> SymbolAnalysisService:
    return SymbolAnalysisService(get_longbridge_external_data_client(), get_llm_service())


def get_symbol_suggest_service() -> SymbolSuggestService:
    return SymbolSuggestService(get_es_client(), get_settings(), get_llm_service(), get_longbridge_external_data_client())


def get_trade_review_repository() -> TradeReviewRepository:
    return TradeReviewRepository(get_es_client(), get_settings())


def get_trade_decision_repository() -> TradeDecisionRepository:
    return TradeDecisionRepository(get_es_client(), get_settings())


def get_trade_decision_outcome_replay_service() -> TradeDecisionOutcomeReplayService:
    return TradeDecisionOutcomeReplayService(
        get_trade_decision_repository(),
        TradeDecisionOutcomePriceProvider(get_es_client(), get_settings()),
    )


def get_daily_position_review_repository() -> DailyPositionReviewRepository:
    return DailyPositionReviewRepository(get_es_client(), get_settings())


def get_daily_position_review_service() -> DailyPositionReviewService:
    return DailyPositionReviewService(
        get_es_client(),
        get_settings(),
        get_longbridge_external_data_client(),
    )


def get_daily_account_snapshot_service() -> DailyAccountSnapshotService:
    return DailyAccountSnapshotService(
        get_es_client(),
        get_settings(),
        get_daily_position_review_service(),
    )


def get_trade_decision_evidence_builder() -> TradeDecisionEvidenceBuilder:
    return TradeDecisionEvidenceBuilder(
        get_es_client(),
        get_settings(),
        get_longbridge_external_data_client(),
        TradeDecisionMetricsCalculator(),
    )


def get_trade_decision_account_facts_builder() -> "TradeDecisionAccountFactsBuilder":
    from app.services.trade_decision_account_facts import TradeDecisionAccountFactsBuilder
    return TradeDecisionAccountFactsBuilder(get_es_client(), get_settings())


def get_trade_review_agent() -> TradeReviewAgent:
    settings = get_settings()
    evidence_builder = TradeReviewEvidenceBuilder(
        get_es_client(),
        settings,
        get_longbridge_external_data_client(),
        TradeReviewMetricsCalculator(),
    )
    return TradeReviewAgent(
        evidence_builder,
        get_llm_service(),
        get_trade_review_repository(),
        prompt_service=get_admin_prompt_service(),
        trace_service=get_agent_run_trace_service(),
        replay_service=get_agent_replay_service(),
        monitoring_service=get_account_copilot_monitoring_service(
            repository=get_account_copilot_monitoring_repository(),
        ),
        investment_policy_service=get_investment_policy_service(),
    )


def get_trade_decision_agent() -> TradeDecisionAgent:
    return TradeDecisionAgent(
        get_trade_decision_evidence_builder(),
        get_llm_service(),
        get_trade_decision_repository(),
        prompt_service=get_admin_prompt_service(),
        trace_service=get_agent_run_trace_service(),
        replay_service=get_agent_replay_service(),
        monitoring_service=get_account_copilot_monitoring_service(
            repository=get_account_copilot_monitoring_repository(),
        ),
    )


def get_daily_position_review_agent() -> DailyPositionReviewAgent:
    review_service = get_daily_position_review_service()
    longbridge_client = get_longbridge_external_data_client()
    related_asset_service = DailyReviewRelatedAssetService(longbridge_client, get_settings())
    prompt_service = get_admin_prompt_service()
    symbol_agent = DailyReviewSymbolEvidenceAgent(get_llm_service(), prompt_service=prompt_service)
    macro_agent = DailyReviewMacroEvidenceAgent(get_llm_service(), prompt_service=prompt_service)
    return DailyPositionReviewAgent(
        review_service,
        get_llm_service(),
        get_daily_position_review_repository(),
        email_service=get_email_service(),
        related_asset_service=related_asset_service,
        longbridge_client=longbridge_client,
        symbol_agent=symbol_agent,
        macro_agent=macro_agent,
        prompt_service=prompt_service,
        trace_service=get_agent_run_trace_service(),
        replay_service=get_agent_replay_service(),
        monitoring_service=get_account_copilot_monitoring_service(
            repository=get_account_copilot_monitoring_repository(),
        ),
    )


def get_daily_review_related_asset_service() -> DailyReviewRelatedAssetService:
    return DailyReviewRelatedAssetService(
        get_longbridge_external_data_client(),
        get_settings(),
    )


def get_risk_assessment_repository() -> RiskAssessmentRepository:
    return RiskAssessmentRepository(get_es_client(), get_settings())


def get_risk_assessment_account_facts_builder():
    from app.services.risk_assessment_account_facts import RiskAssessmentAccountFactsBuilder
    return RiskAssessmentAccountFactsBuilder(get_es_client(), get_settings())


def _get_mcp_adapter():
    from app.services.mcp.longbridge_mcp_client import LongbridgeMCPClient, get_longbridge_mcp_config
    from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter

    settings = get_settings()
    client = LongbridgeMCPClient(
        config=get_longbridge_mcp_config(settings),
        settings=settings,
        token_service=get_longbridge_oauth_token_service(),
    )
    return LongbridgeMCPToolAdapter(client)


def _get_optional_mcp_adapter():
    try:
        return _get_mcp_adapter()
    except Exception as exc:
        logger.warning("Longbridge MCP adapter unavailable for Account Copilot: %s", exc)
        return None


def get_risk_assessment_agent() -> RiskAssessmentAgent:
    return RiskAssessmentAgent(
        get_risk_assessment_account_facts_builder(),
        get_llm_service(),
        get_risk_assessment_repository(),
        _get_optional_mcp_adapter(),
        monitoring_service=get_account_copilot_monitoring_service(
            repository=get_account_copilot_monitoring_repository(),
        ),
    )


def get_optional_auth_session(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AuthSession | None:
    if not session_token:
        return None

    from app.services.admin_bootstrap_service import AdminAuthService

    auth_service = AdminAuthService(get_settings())
    return verify_session_token(session_token, secret=auth_service.get_session_secret())


def require_authenticated_session(
    auth_session: AuthSession | None = Depends(get_optional_auth_session),
) -> AuthSession:
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录后查看该模块")

    return auth_session


def require_admin_session(
    auth_session: AuthSession = Depends(require_authenticated_session),
) -> AuthSession:
    return auth_session
