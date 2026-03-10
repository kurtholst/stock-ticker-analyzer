"""Stock data fetching and technical analysis via yfinance."""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class QuoteData(BaseModel):
    ticker: str
    name: str
    price: float
    change: float
    change_pct: float
    day_high: float
    day_low: float
    week52_high: float
    week52_low: float
    market_cap: float | None = None
    volume: int | None = None
    sparkline: list[float]


class HistoryRequest(BaseModel):
    tickers: list[str]
    period: str = "1mo"


class OHLCVRow(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class TickerHistory(BaseModel):
    ticker: str
    data: list[OHLCVRow]
    normalized: list[float]


class HistoryResponse(BaseModel):
    tickers: list[TickerHistory]
    dates: list[str]


class TechnicalsRequest(BaseModel):
    ticker: str
    period: str = "1y"


class TechnicalsResponse(BaseModel):
    ticker: str
    dates: list[str]
    close: list[float]
    sma20: list[float | None]
    sma50: list[float | None]
    ema12: list[float | None]
    ema26: list[float | None]
    bb_upper: list[float | None]
    bb_middle: list[float | None]
    bb_lower: list[float | None]
    rsi: list[float | None]
    macd: list[float | None]
    macd_signal: list[float | None]
    macd_hist: list[float | None]
    volume: list[int]


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def validate_ticker(ticker: str) -> bool:
    try:
        t = yf.Ticker(ticker)
        info = t.info
        return info.get("regularMarketPrice") is not None or info.get("currentPrice") is not None
    except Exception:
        return False


def get_quote(ticker: str) -> QuoteData:
    t = yf.Ticker(ticker)
    info = t.info

    price = info.get("regularMarketPrice") or info.get("currentPrice") or 0.0
    prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose") or price
    change = price - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0

    # Sparkline: 30 days of closing prices (drop NaN)
    hist = t.history(period="1mo")
    sparkline = hist["Close"].dropna().tolist() if not hist.empty else []

    return QuoteData(
        ticker=ticker,
        name=info.get("shortName") or info.get("longName") or ticker,
        price=price,
        change=round(change, 2),
        change_pct=round(change_pct, 2),
        day_high=info.get("dayHigh") or info.get("regularMarketDayHigh") or 0.0,
        day_low=info.get("dayLow") or info.get("regularMarketDayLow") or 0.0,
        week52_high=info.get("fiftyTwoWeekHigh") or 0.0,
        week52_low=info.get("fiftyTwoWeekLow") or 0.0,
        market_cap=info.get("marketCap"),
        volume=info.get("volume") or info.get("regularMarketVolume"),
        sparkline=sparkline,
    )


def _fetch_one_ticker(ticker: str, period: str) -> TickerHistory | None:
    """Fetch history for a single ticker (designed to run in a thread)."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist.empty:
            return None

        # Drop rows with NaN close prices (weekends, holidays, pre-market)
        hist = hist.dropna(subset=["Close"])
        if hist.empty:
            return None

        dates = [d.strftime("%Y-%m-%d") for d in hist.index]
        closes = hist["Close"].tolist()
        base = closes[0] if closes else 1.0
        normalized = [round((c / base - 1) * 100, 2) for c in closes]

        def _safe(v: float) -> float:
            return 0.0 if pd.isna(v) else round(v, 2)

        rows = [
            OHLCVRow(
                date=d,
                open=_safe(row.Open),
                high=_safe(row.High),
                low=_safe(row.Low),
                close=_safe(row.Close),
                volume=int(row.Volume) if not pd.isna(row.Volume) else 0,
            )
            for d, row in zip(dates, hist.itertuples())
        ]

        return TickerHistory(ticker=ticker, data=rows, normalized=normalized)
    except Exception:
        return None


def get_history(request: HistoryRequest) -> HistoryResponse:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(request.tickers)) as pool:
        futures = [pool.submit(_fetch_one_ticker, t, request.period) for t in request.tickers]
        results = [f.result() for f in futures]

    ticker_histories = [r for r in results if r is not None]
    all_dates = ticker_histories[0].data and [row.date for row in ticker_histories[0].data] if ticker_histories else []

    return HistoryResponse(tickers=ticker_histories, dates=all_dates)


# ---------------------------------------------------------------------------
# Technical indicators
# ---------------------------------------------------------------------------

def _sma(series: pd.Series, window: int) -> list[float | None]:
    result = series.rolling(window=window).mean()
    return [None if pd.isna(v) else round(v, 2) for v in result]


def _ema(series: pd.Series, span: int) -> list[float | None]:
    result = series.ewm(span=span, adjust=False).mean()
    return [None if pd.isna(v) else round(v, 2) for v in result]


def _bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0):
    middle = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    to_list = lambda s: [None if pd.isna(v) else round(v, 2) for v in s]
    return to_list(upper), to_list(middle), to_list(lower)


def _rsi(series: pd.Series, period: int = 14) -> list[float | None]:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return [None if pd.isna(v) else round(v, 2) for v in rsi]


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    to_list = lambda s: [None if pd.isna(v) else round(v, 4) for v in s]
    return to_list(macd_line), to_list(signal_line), to_list(histogram)


def get_technicals(request: TechnicalsRequest) -> TechnicalsResponse:
    t = yf.Ticker(request.ticker)
    hist = t.history(period=request.period)

    close = hist["Close"]
    dates = [d.strftime("%Y-%m-%d") for d in hist.index]

    bb_upper, bb_middle, bb_lower = _bollinger(close)
    macd_line, macd_signal, macd_hist = _macd(close)

    return TechnicalsResponse(
        ticker=request.ticker,
        dates=dates,
        close=[round(v, 2) for v in close],
        sma20=_sma(close, 20),
        sma50=_sma(close, 50),
        ema12=_ema(close, 12),
        ema26=_ema(close, 26),
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        rsi=_rsi(close),
        macd=macd_line,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
        volume=[int(v) for v in hist["Volume"]],
    )
