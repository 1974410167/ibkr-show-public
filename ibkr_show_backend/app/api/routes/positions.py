from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_position_service
from app.clients.es_client import ESClientError
from app.schemas.positions import PositionDetailResponse, PositionListResponse, PositionSummaryResponse
from app.services.position_service import PositionService

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("", response_model=PositionListResponse)
def list_positions(
    report_date: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    asset_class: str | None = Query(default=None),
    include_summary: bool = Query(default=False),
    sort_by: str = Query(default="position_value"),
    sort_order: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: PositionService = Depends(get_position_service),
) -> PositionListResponse:
    try:
        return service.list_positions(
            report_date=report_date,
            symbol=symbol,
            asset_class=asset_class,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
            include_summary=include_summary,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ESClientError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/summary", response_model=PositionSummaryResponse)
def get_positions_summary(
    report_date: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    asset_class: str | None = Query(default=None),
    service: PositionService = Depends(get_position_service),
) -> PositionSummaryResponse:
    try:
        return service.get_positions_summary(
            report_date=report_date,
            symbol=symbol,
            asset_class=asset_class,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ESClientError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/detail", response_model=PositionDetailResponse)
def get_position_detail(
    symbol: str = Query(),
    asset_class: str | None = Query(default=None),
    service: PositionService = Depends(get_position_service),
) -> PositionDetailResponse:
    try:
        return service.get_position_detail(symbol=symbol, asset_class=asset_class)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ESClientError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
