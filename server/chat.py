"""Chat module — daytrading insights powered by Databricks Foundation Model API."""

from __future__ import annotations

import json

from openai import OpenAI
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class TickerContext(BaseModel):
    tickers: list[str]
    quotes: list[dict] | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    ticker_context: TickerContext | None = None


class ChatResponse(BaseModel):
    reply: str
    model: str


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a knowledgeable stock market analyst integrated into a daytrading-oriented stock ticker analyzer app. You help users understand stock movements, technical indicators, and market trends.

**Your capabilities:**
- Analyze price movements, volume patterns, and technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands).
- Explain what technical signals mean for potential trading decisions.
- Compare multiple stocks and identify relative strength/weakness.
- Discuss market context, sector trends, and relevant news themes.
- Interpret chart patterns and suggest what to watch for.

**Rules:**
- Never give specific buy/sell recommendations. You are an educational and analytical tool.
- When ticker data is available, reference actual numbers (e.g., "AAPL's RSI at 72 suggests overbought conditions").
- Suggest indicators or timeframes the user can explore in the app.
- Keep answers concise (2-4 paragraphs max).
- Respond in the same language the user writes in.
"""

# ---------------------------------------------------------------------------
# Databricks auth + OpenAI client
# ---------------------------------------------------------------------------

MODEL = "databricks-gpt-5.2"


def _get_client() -> OpenAI:
    from databricks.sdk import WorkspaceClient

    ws = WorkspaceClient()
    host = ws.config.host.rstrip("/")

    headers = ws.config.authenticate()
    token = headers.get("Authorization", "").removeprefix("Bearer ")

    return OpenAI(base_url=f"{host}/serving-endpoints", api_key=token)


# ---------------------------------------------------------------------------
# Chat handler
# ---------------------------------------------------------------------------

def get_chat_response(request: ChatRequest) -> ChatResponse:
    client = _get_client()

    system_content = SYSTEM_PROMPT
    if request.ticker_context:
        ctx = request.ticker_context
        system_content += f"\n\n**Active tickers:** {', '.join(ctx.tickers)}\n"
        if ctx.quotes:
            system_content += f"**Current quotes:** {json.dumps(ctx.quotes, default=str)}\n"

    messages = [{"role": "system", "content": system_content}]
    for msg in request.messages:
        messages.append({"role": msg.role, "content": msg.content})

    completion = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=1024,
        temperature=0.7,
    )

    content = completion.choices[0].message.content

    if isinstance(content, list):
        reply = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
            if not isinstance(block, dict) or block.get("type") != "reasoning"
        )
    else:
        reply = content or ""

    return ChatResponse(reply=reply, model=MODEL)
