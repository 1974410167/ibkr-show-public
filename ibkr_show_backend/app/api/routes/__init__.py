from fastapi import APIRouter

from app.api.routes.account import router as account_router
from app.api.routes.account_copilot import router as account_copilot_router
from app.api.routes.admin_email import router as admin_email_router
from app.api.routes.admin_ibkr import router as admin_ibkr_router
from app.api.routes.admin_agent_replays import router as admin_agent_replays_router
from app.api.routes.admin_agent_runs import router as admin_agent_runs_router
from app.api.routes.admin_agent_eval import router as admin_agent_eval_router
from app.api.routes.admin_longbridge_openapi import router as admin_longbridge_openapi_router
from app.api.routes.admin_longbridge_mcp import router as admin_longbridge_mcp_router
from app.api.routes.admin_llm import router as admin_llm_router
from app.api.routes.admin_market_events import router as admin_market_events_router
from app.api.routes.admin_llm_calls import router as admin_llm_calls_router
from app.api.routes.admin_prompts import router as admin_prompts_router
from app.api.routes.admin_system import router as admin_system_router
from app.api.routes.agent_tasks import router as agent_tasks_router
from app.api.routes.auth import router as auth_router
from app.api.routes.cash_flows import router as cash_flows_router
from app.api.routes.charts import router as charts_router
from app.api.routes.daily_account_snapshot_email import router as daily_account_snapshot_email_router
from app.api.routes.daily_position_review import router as daily_position_review_router
from app.api.routes.dividends import router as dividends_router
from app.api.routes.health import router as health_router
from app.api.routes.investment_policy import router as investment_policy_router
from app.api.routes.longbridge import router as longbridge_router
from app.api.routes.market_events import router as market_events_router
from app.api.routes.positions import router as positions_router
from app.api.routes.risk_assessment_agent import router as risk_assessment_agent_router
from app.api.routes.symbol_analysis import router as symbol_analysis_router
from app.api.routes.symbols import router as symbols_router
from app.api.routes.trade_decision_agent import router as trade_decision_agent_router
from app.api.routes.trade_review_agent import router as trade_review_agent_router
from app.api.routes.trades import router as trades_router

api_router = APIRouter(prefix="/api")
api_router.include_router(account_router)
api_router.include_router(account_copilot_router)
api_router.include_router(admin_email_router)
api_router.include_router(admin_ibkr_router)
api_router.include_router(admin_agent_replays_router)
api_router.include_router(admin_agent_runs_router)
api_router.include_router(admin_agent_eval_router)
api_router.include_router(admin_longbridge_openapi_router)
api_router.include_router(admin_longbridge_mcp_router)
api_router.include_router(admin_llm_router)
api_router.include_router(admin_llm_calls_router)
api_router.include_router(admin_market_events_router)
api_router.include_router(admin_prompts_router)
api_router.include_router(admin_system_router)
api_router.include_router(agent_tasks_router)
api_router.include_router(auth_router)
api_router.include_router(cash_flows_router)
api_router.include_router(charts_router)
api_router.include_router(daily_account_snapshot_email_router)
api_router.include_router(daily_position_review_router)
api_router.include_router(dividends_router)
api_router.include_router(investment_policy_router)
api_router.include_router(longbridge_router)
api_router.include_router(market_events_router)
api_router.include_router(positions_router)
api_router.include_router(risk_assessment_agent_router)
api_router.include_router(symbol_analysis_router)
api_router.include_router(symbols_router)
api_router.include_router(trade_decision_agent_router)
api_router.include_router(trade_review_agent_router)
api_router.include_router(trades_router)

__all__ = ["api_router", "health_router"]
