from fastapi import APIRouter

from .analysis import (
    HistoryRequest,
    TechnicalsRequest,
    get_history,
    get_quote,
    get_technicals,
    validate_ticker,
)
from .chat import ChatRequest, get_chat_response

router = APIRouter()

DEFAULT_TICKERS = ["SAP", "AAPL", "AMZN", "NOVO-B.CO"]


@router.get("/defaults")
async def get_defaults() -> dict:
    return {"tickers": DEFAULT_TICKERS}


@router.get("/quote/{ticker}")
async def quote(ticker: str) -> dict:
    data = get_quote(ticker)
    return data.model_dump()


@router.get("/validate/{ticker}")
async def validate(ticker: str) -> dict:
    valid = validate_ticker(ticker)
    return {"ticker": ticker, "valid": valid}


@router.post("/history")
async def history(request: HistoryRequest) -> dict:
    data = get_history(request)
    return data.model_dump()


@router.post("/technicals")
async def technicals(request: TechnicalsRequest) -> dict:
    data = get_technicals(request)
    return data.model_dump()


@router.post("/chat")
async def chat(request: ChatRequest) -> dict:
    response = get_chat_response(request)
    return response.model_dump()
