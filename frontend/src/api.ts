import type { QuoteData, HistoryResponse, TechnicalsResponse, ChatResponseData } from './types';

export async function fetchDefaults(): Promise<{ tickers: string[] }> {
  const res = await fetch('/api/defaults');
  if (!res.ok) throw new Error('Failed to fetch defaults');
  return res.json();
}

export async function fetchQuote(ticker: string): Promise<QuoteData> {
  const res = await fetch(`/api/quote/${encodeURIComponent(ticker)}`);
  if (!res.ok) throw new Error(`Failed to fetch quote for ${ticker}`);
  return res.json();
}

export async function validateTicker(ticker: string): Promise<{ ticker: string; valid: boolean }> {
  const res = await fetch(`/api/validate/${encodeURIComponent(ticker)}`);
  if (!res.ok) throw new Error(`Failed to validate ${ticker}`);
  return res.json();
}

export async function fetchHistory(tickers: string[], period: string): Promise<HistoryResponse> {
  const res = await fetch('/api/history', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tickers, period }),
  });
  if (!res.ok) throw new Error('Failed to fetch history');
  return res.json();
}

export async function fetchTechnicals(ticker: string, period: string): Promise<TechnicalsResponse> {
  const res = await fetch('/api/technicals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ticker, period }),
  });
  if (!res.ok) throw new Error('Failed to fetch technicals');
  return res.json();
}

export async function sendChatMessage(
  messages: { role: string; content: string }[],
  tickerContext?: { tickers: string[]; quotes?: Record<string, unknown>[] },
): Promise<ChatResponseData> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, ticker_context: tickerContext }),
  });
  if (!res.ok) throw new Error('Chat request failed');
  return res.json();
}
