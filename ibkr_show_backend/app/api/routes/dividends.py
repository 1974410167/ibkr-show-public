from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_dividend_service, require_authenticated_session
from app.clients.es_client import ESClientError
from app.core.auth import AuthSession
from app.schemas.dividends import DividendListResponse, DividendSummaryResponse
from app.services.dividend_service import DividendService

router = APIRouter(prefix="/dividends", tags=["dividends"])


@router.get("", response_model=DividendListResponse)
def list_dividends(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    currency: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    sort_by: str = Query(default="date_time"),
    sort_order: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: DividendService = Depends(get_dividend_service),
) -> DividendListResponse:
    try:
        return service.list_dividends(
            start_date=start_date,
            end_date=end_date,
            currency=currency,
            symbol=symbol,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ESClientError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/summary", response_model=DividendSummaryResponse)
def get_dividend_summary(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    currency: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: DividendService = Depends(get_dividend_service),
) -> DividendSummaryResponse:
    try:
        return service.summarize_dividends(
            start_date=start_date,
            end_date=end_date,
            currency=currency,
            symbol=symbol,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ESClientError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
