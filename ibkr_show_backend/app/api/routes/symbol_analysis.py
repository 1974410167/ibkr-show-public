from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_symbol_analysis_service, require_authenticated_session
from app.core.auth import AuthSession
from app.schemas.symbol_analysis import (
    SymbolAiAdviceRequest,
    SymbolAiAdviceResponse,
    SymbolComparisonResponse,
    SymbolFinancialsResponse,
)
from app.services.llm_service import LLMClientError, LLMConfigError
from app.services.longbridge_service import LongbridgeExternalDataError, LongbridgeUnavailableError
from app.services.symbol_analysis_service import SymbolAnalysisService

router = APIRouter(prefix="/symbol-analysis", tags=["symbol-analysis"])


@router.get("/{symbol}/financials", response_model=SymbolFinancialsResponse)
def get_symbol_financials(
    symbol: str,
    periods: int = Query(default=8, ge=1, le=12),
    report: str = Query(default="qf"),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: SymbolAnalysisService = Depends(get_symbol_analysis_service),
) -> SymbolFinancialsResponse:
    try:
        return service.get_financials(symbol=symbol, periods=periods, report=report)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LongbridgeUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except LongbridgeExternalDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/compare", response_model=SymbolComparisonResponse)
def compare_symbols(
    left: str = Query(...),
    right: str = Query(...),
    periods: int = Query(default=8, ge=1, le=12),
    report: str = Query(default="qf"),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: SymbolAnalysisService = Depends(get_symbol_analysis_service),
) -> SymbolComparisonResponse:
    try:
        return service.compare(left_symbol=left, right_symbol=right, periods=periods, report=report)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LongbridgeUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except LongbridgeExternalDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/compare/ai-advice", response_model=SymbolAiAdviceResponse)
def generate_symbol_ai_advice(
    payload: SymbolAiAdviceRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: SymbolAnalysisService = Depends(get_symbol_analysis_service),
) -> SymbolAiAdviceResponse:
    try:
        return service.generate_ai_advice(
            left_symbol=payload.left_symbol,
            right_symbol=payload.right_symbol,
            question=payload.question,
            comparison=payload.comparison,
        )
    except LLMClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error_code": exc.error_code, "message": exc.message}) from exc
    except (ValueError, LLMConfigError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LongbridgeUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except LongbridgeExternalDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
