from fastapi import APIRouter

from app.api.routes.account import router as account_router
from app.api.routes.auth import router as auth_router
from app.api.routes.cash_flows import router as cash_flows_router
from app.api.routes.charts import router as charts_router
from app.api.routes.dividends import router as dividends_router
from app.api.routes.health import router as health_router
from app.api.routes.positions import router as positions_router
from app.api.routes.trades import router as trades_router

api_router = APIRouter(prefix="/api")
api_router.include_router(account_router)
api_router.include_router(auth_router)
api_router.include_router(cash_flows_router)
api_router.include_router(charts_router)
api_router.include_router(dividends_router)
api_router.include_router(positions_router)
api_router.include_router(trades_router)

__all__ = ["api_router", "health_router"]
