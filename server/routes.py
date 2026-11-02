import logging

from fastapi import APIRouter
from pydantic import BaseModel

from .analysis import (
    HistoryRequest,
    RankRequest,
    TechnicalsRequest,
    get_history,
    get_quote,
    get_rank,
    get_technicals,
    validate_ticker,
)
from .chat import ChatRequest, get_chat_response
from .db import execute_sql
from .patents import (
    PatentAnalyzeRequest,
    PatentAnalyzeResponse,
    PatentSearchResponse,
    _company_name_for_ticker,
    analyze_patents_with_gemini,
    search_epo_patents,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class TickersPayload(BaseModel):
    tickers: list[str]


def _read_tickers() -> list[str]:
    """Read active tickers from the sta_tickers Delta table."""
    rows = execute_sql(
        "SELECT ticker FROM workspace.default.sta_tickers "
        "WHERE is_active = true ORDER BY ticker"
    )
    return [r["ticker"] for r in rows]


def _write_tickers(tickers: list[str]) -> None:
    """Sync the sta_tickers table to match the given list.

    Deactivates all current tickers, then upserts each requested ticker
    as active.
    """
    # Deactivate all
    execute_sql(
        "UPDATE workspace.default.sta_tickers SET is_active = false "
        "WHERE is_active = true"
    )
    # Upsert each ticker as active
    for t in tickers:
        execute_sql(
            "MERGE INTO workspace.default.sta_tickers AS target "
            "USING (SELECT :ticker AS ticker) AS source "
            "ON target.ticker = source.ticker "
            "WHEN MATCHED THEN UPDATE SET is_active = true "
            "WHEN NOT MATCHED THEN INSERT (ticker, added_at, is_active) "
            "VALUES (source.ticker, current_timestamp(), true)",
            parameters={"ticker": t},
        )


@router.get("/tickers")
def get_tickers() -> dict:
    return {"tickers": _read_tickers()}


@router.put("/tickers")
def put_tickers(payload: TickersPayload) -> dict:
    _write_tickers(payload.tickers)
    return {"tickers": payload.tickers}


@router.get("/quote/{ticker}")
def quote(ticker: str) -> dict:
    data = get_quote(ticker)
    return data.model_dump()


@router.get("/validate/{ticker}")
def validate(ticker: str) -> dict:
    valid = validate_ticker(ticker)
    return {"ticker": ticker, "valid": valid}


@router.post("/history")
def history(request: HistoryRequest) -> dict:
    data = get_history(request)
    return data.model_dump()


@router.post("/technicals")
def technicals(request: TechnicalsRequest) -> dict:
    data = get_technicals(request)
    return data.model_dump()


@router.post("/rank")
def rank(request: RankRequest) -> list[dict]:
    rows = get_rank(request)
    return [r.model_dump() for r in rows]


@router.post("/chat")
def chat(request: ChatRequest) -> dict:
    response = get_chat_response(request)
    return response.model_dump()


# --- Patent endpoints ---


@router.get("/patents/{ticker}")
async def get_patents(ticker: str) -> dict:
    """Search EPO OPS for recent patents by portfolio company."""
    company_name = _company_name_for_ticker(ticker)
    patents, error = await search_epo_patents(company_name)
    resp = PatentSearchResponse(
        ticker=ticker,
        company_name=company_name,
        patents=patents,
        total_found=len(patents),
        source="EPO Espacenet",
        error=error,
    )
    return resp.model_dump()


@router.post("/patents/analyze")
async def post_patent_analyze(request: PatentAnalyzeRequest) -> dict:
    """Analyze patents with Gemini 2.5 Flash AI."""
    resp = await analyze_patents_with_gemini(
        patents=request.patents,
        company_name=request.company_name,
        ticker=request.ticker,
    )
    return resp.model_dump()
