from functools import lru_cache

from fastapi import Cookie, Depends, HTTPException, status

from app.clients.es_client import ElasticsearchClient
from app.clients.cache_client import RedisCacheClient
from app.core.auth import SESSION_COOKIE_NAME, AuthSession, verify_session_token
from app.core.config import get_settings
from app.services.account_service import AccountService
from app.services.cash_flow_service import CashFlowService
from app.services.chart_service import ChartService
from app.services.dividend_service import DividendService
from app.services.position_service import PositionService
from app.services.trade_service import TradeService


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


def get_optional_auth_session(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AuthSession | None:
    if not session_token:
        return None

    return verify_session_token(session_token, secret=get_settings().auth_session_secret)


def require_authenticated_session(
    auth_session: AuthSession | None = Depends(get_optional_auth_session),
) -> AuthSession:
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录后查看该模块")

    return auth_session
