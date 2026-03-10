# Databricks notebook source
# COMMAND ----------
"""
Fetch stock data from Finnhub and write to Delta tables.

Runs on serverless compute.
Scheduled to run every 10 minutes during market hours.

Data provider: Finnhub (https://finnhub.io)
  - Quotes: real-time price, open, high, low, change
  - Company profiles: name, market cap
  - Daily OHLCV row derived from quote data

Historical OHLCV is pre-loaded via backfill. This job appends/updates
today's row from the Finnhub quote endpoint.

API key stored in Databricks secrets:
  scope: "stock-ticker-analyzer", key: "finnhub-api-key"
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"

# COMMAND ----------
# Resolve API key

api_key = dbutils.secrets.get(scope="stock-ticker-analyzer", key="finnhub-api-key")
logger.info("Finnhub API key loaded (length=%d)", len(api_key))

# COMMAND ----------


def _get(endpoint: str, params: dict) -> dict:
    """Make a GET request to Finnhub API."""
    params["token"] = api_key
    resp = requests.get(f"{FINNHUB_BASE}{endpoint}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_quote(ticker: str) -> dict | None:
    """Fetch real-time quote from Finnhub. Returns None for unsupported tickers."""
    try:
        q = _get("/quote", {"symbol": ticker})
    except Exception:
        logger.info("Finnhub quote unavailable for %s (likely non-US ticker)", ticker)
        return None
    if not q or q.get("c") is None or q["c"] == 0:
        logger.info("No quote data for %s (Finnhub free tier may not cover this exchange)", ticker)
        return None
    return {
        "price": float(q["c"]),
        "open": float(q.get("o") or 0),
        "high": float(q.get("h") or 0),
        "low": float(q.get("l") or 0),
        "change": float(q.get("d") or 0),
        "change_pct": float(q.get("dp") or 0),
        "prev_close": float(q.get("pc") or 0),
    }


def fetch_profile(ticker: str) -> dict:
    """Fetch company profile (name, market cap)."""
    try:
        p = _get("/stock/profile2", {"symbol": ticker})
        return {
            "name": p.get("name") or ticker,
            "market_cap": float(p["marketCapitalization"]) * 1e6 if p.get("marketCapitalization") else None,
        }
    except Exception:
        return {"name": ticker, "market_cap": None}


# COMMAND ----------


def fetch_ticker_data(ticker: str) -> dict | None:
    """Fetch all data for a single ticker."""
    try:
        quote = fetch_quote(ticker)
        profile = fetch_profile(ticker)
        if not quote:
            return None
        return {"ticker": ticker, "quote": quote, "profile": profile}
    except Exception:
        logger.exception("Failed to fetch %s", ticker)
        return None


# COMMAND ----------
# Read active tickers

tickers_df = spark.sql(
    "SELECT ticker FROM workspace.default.sta_tickers WHERE is_active = true"
)
tickers = [row.ticker for row in tickers_df.collect()]
logger.info("Active tickers: %s", tickers)

if not tickers:
    logger.warning("No active tickers found. Exiting.")
    dbutils.notebook.exit("No active tickers")

# COMMAND ----------
# Fetch 52-week high/low from existing OHLCV data

week52_data = {}
for ticker in tickers:
    try:
        row = spark.sql(f"""
            SELECT MAX(high) as w52_high, MIN(low) as w52_low
            FROM workspace.default.sta_ohlcv
            WHERE ticker = '{ticker}' AND date >= date_sub(current_date(), 365)
        """).first()
        week52_data[ticker] = {
            "high": float(row.w52_high) if row.w52_high else 0.0,
            "low": float(row.w52_low) if row.w52_low else 0.0,
        }
    except Exception:
        week52_data[ticker] = {"high": 0.0, "low": 0.0}

# COMMAND ----------
# Fetch data in parallel (Finnhub free: 60 calls/min)

all_quotes = []
all_ohlcv = []
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

with ThreadPoolExecutor(max_workers=min(len(tickers), 8)) as pool:
    futures = {pool.submit(fetch_ticker_data, t): t for t in tickers}
    for future in as_completed(futures):
        ticker = futures[future]
        data = future.result()
        if data is None:
            continue
        q = data["quote"]
        p = data["profile"]
        w52 = week52_data.get(ticker, {"high": 0.0, "low": 0.0})

        # Build quote row
        all_quotes.append({
            "ticker": ticker,
            "name": p["name"],
            "price": q["price"],
            "change": q["change"],
            "change_pct": q["change_pct"],
            "day_high": q["high"],
            "day_low": q["low"],
            "week52_high": max(w52["high"], q["high"]),
            "week52_low": min(w52["low"], q["low"]) if w52["low"] > 0 else q["low"],
            "market_cap": p["market_cap"],
            "volume": 0,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        })

        # Build today's OHLCV row from quote
        all_ohlcv.append({
            "ticker": ticker,
            "date": today,
            "open": q["open"],
            "high": q["high"],
            "low": q["low"],
            "close": q["price"],
            "volume": 0,
        })

logger.info("Fetched %d quotes, %d OHLCV rows", len(all_quotes), len(all_ohlcv))

# COMMAND ----------
# Write quotes via MERGE

if all_quotes:
    quotes_df = spark.createDataFrame(all_quotes)
    quotes_df.createOrReplaceTempView("new_quotes")
    spark.sql("""
        MERGE INTO workspace.default.sta_quotes AS target
        USING new_quotes AS source
        ON target.ticker = source.ticker
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)
    logger.info("Merged %d quotes into sta_quotes", len(all_quotes))

# COMMAND ----------
# Write today's OHLCV via MERGE (updates intraday as prices change)

if all_ohlcv:
    ohlcv_df = spark.createDataFrame(all_ohlcv)
    ohlcv_df.createOrReplaceTempView("new_ohlcv")
    spark.sql("""
        MERGE INTO workspace.default.sta_ohlcv AS target
        USING new_ohlcv AS source
        ON target.ticker = source.ticker AND target.date = source.date
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)
    logger.info("Merged %d OHLCV rows into sta_ohlcv", len(all_ohlcv))

# COMMAND ----------
# Summary

results = []
for ticker in tickers:
    count = spark.sql(
        f"SELECT count(*) AS cnt FROM workspace.default.sta_ohlcv WHERE ticker = '{ticker}'"
    ).first().cnt
    q_count = spark.sql(
        f"SELECT count(*) AS cnt FROM workspace.default.sta_quotes WHERE ticker = '{ticker}'"
    ).first().cnt
    results.append(f"{ticker}: {count} OHLCV rows, {q_count} quote rows")

logger.info("Results: %s", results)
dbutils.notebook.exit(json.dumps(results))
