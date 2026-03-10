# Databricks notebook source
# COMMAND ----------
# %md
# # Danish Stocks Available on Finnhub
# Lists all stocks on the Copenhagen Stock Exchange (Nasdaq Copenhagen, exchange code `CO`).

# COMMAND ----------
import requests, json

api_key = dbutils.secrets.get(scope="stock-ticker-analyzer", key="finnhub-api-key")

resp = requests.get(
    f"https://finnhub.io/api/v1/stock/symbol?exchange=CO&token={api_key}",
    timeout=30,
)
resp.raise_for_status()
symbols = resp.json()

print(f"Total Danish stocks on Finnhub: {len(symbols)}")

# COMMAND ----------
# Build a Spark DataFrame for easy browsing

from pyspark.sql.functions import col

rows = [
    {
        "symbol": s.get("symbol", ""),
        "description": s.get("description", ""),
        "type": s.get("type", ""),
        "currency": s.get("currency", ""),
        "figi": s.get("figi", ""),
        "mic": s.get("mic", ""),
    }
    for s in symbols
]

df = spark.createDataFrame(rows)
df = df.select("symbol", "description", "type", "currency", "mic", "figi") \
       .orderBy("description")

display(df)

# COMMAND ----------
# Filter: Common Stocks only

common = df.filter(col("type") == "Common Stock")
print(f"Common stocks: {common.count()}")
display(common)

# COMMAND ----------
# Quick search — find Novo Nordisk, DSV, Carlsberg, etc.

search_terms = ["NOVO", "DSV", "CARLSBERG", "MAERSK", "VESTAS", "ORSTED", "PANDORA", "COLOPLAST", "DEMANT", "GENMAB"]
for term in search_terms:
    matches = df.filter(col("description").contains(term) | col("symbol").contains(term))
    for row in matches.collect():
        print(f"  {row.symbol:20s} {row.description:40s} {row.type}")
    if matches.count() == 0:
        print(f"  {term}: no match")
