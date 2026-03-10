export interface QuoteData {
  ticker: string;
  name: string;
  price: number;
  change: number;
  change_pct: number;
  day_high: number;
  day_low: number;
  week52_high: number;
  week52_low: number;
  market_cap: number | null;
  volume: number | null;
  sparkline: number[];
}

export interface OHLCVRow {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TickerHistory {
  ticker: string;
  data: OHLCVRow[];
  normalized: number[];
}

export interface HistoryResponse {
  tickers: TickerHistory[];
  dates: string[];
}

export interface TechnicalsResponse {
  ticker: string;
  dates: string[];
  close: number[];
  sma20: (number | null)[];
  sma50: (number | null)[];
  ema12: (number | null)[];
  ema26: (number | null)[];
  bb_upper: (number | null)[];
  bb_middle: (number | null)[];
  bb_lower: (number | null)[];
  rsi: (number | null)[];
  macd: (number | null)[];
  macd_signal: (number | null)[];
  macd_hist: (number | null)[];
  volume: number[];
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatResponseData {
  reply: string;
  model: string;
}
