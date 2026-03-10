# Databricks notebook source
# COMMAND ----------
# Bootstrap: Create Delta tables and seed default tickers for
# the Stock Ticker Analyzer app.
#
# Run this notebook ONCE on any cluster before starting the app.

# COMMAND ----------
# 1. sta_tickers — ticker config
spark.sql("""
CREATE TABLE IF NOT EXISTS workspace.default.sta_tickers (
    ticker STRING,
    added_at TIMESTAMP,
    is_active BOOLEAN
)
""")

# COMMAND ----------
# 2. sta_quotes — latest quote snapshot per ticker
spark.sql("""
CREATE TABLE IF NOT EXISTS workspace.default.sta_quotes (
    ticker STRING,
    name STRING,
    price DOUBLE,
    change DOUBLE,
    change_pct DOUBLE,
    day_high DOUBLE,
    day_low DOUBLE,
    week52_high DOUBLE,
    week52_low DOUBLE,
    market_cap DOUBLE,
    volume BIGINT,
    updated_at TIMESTAMP
)
""")

# COMMAND ----------
# 3. sta_ohlcv — daily OHLCV history, partitioned by ticker
spark.sql("""
CREATE TABLE IF NOT EXISTS workspace.default.sta_ohlcv (
    ticker STRING,
    date DATE,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume BIGINT
)
PARTITIONED BY (ticker)
""")

# COMMAND ----------
# 4. Seed default tickers
default_tickers = ["SAP", "AAPL", "AMZN", "NOVO-B.CO"]

for t in default_tickers:
    spark.sql(f"""
        MERGE INTO workspace.default.sta_tickers AS target
        USING (SELECT '{t}' AS ticker) AS source
        ON target.ticker = source.ticker
        WHEN NOT MATCHED THEN
            INSERT (ticker, added_at, is_active)
            VALUES (source.ticker, current_timestamp(), true)
    """)

print(f"Seeded {len(default_tickers)} tickers")

# COMMAND ----------
# Verify
display(spark.sql("SELECT * FROM workspace.default.sta_tickers"))
