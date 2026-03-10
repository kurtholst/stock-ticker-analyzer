import { useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown, Loader2 } from 'lucide-react';
import type { HistoryResponse, OHLCVRow } from '../types';
import { fetchHistory } from '../api';
import { formatPrice, getTickerColor } from '../utils';

const PERIODS = ['5d', '1mo', '3mo', '6mo', '1y'] as const;

type SortKey = 'date' | 'ticker' | 'open' | 'high' | 'low' | 'close' | 'volume';

interface TableRow extends OHLCVRow {
  ticker: string;
}

interface Props {
  tickers: string[];
}

export function DataTable({ tickers }: Props) {
  const [period, setPeriod] = useState<string>('1mo');
  const [filterTicker, setFilterTicker] = useState<string>('all');
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>('date');
  const [sortAsc, setSortAsc] = useState(false);

  useEffect(() => {
    if (tickers.length === 0) return;
    setLoading(true);
    fetchHistory(tickers, period)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [tickers, period]);

  const rows: TableRow[] = useMemo(() => {
    if (!data) return [];
    const all: TableRow[] = [];
    for (const th of data.tickers) {
      for (const row of th.data) {
        all.push({ ...row, ticker: th.ticker });
      }
    }
    return all;
  }, [data]);

  const filtered = useMemo(() => {
    let result = filterTicker === 'all' ? rows : rows.filter((r) => r.ticker === filterTicker);
    result = [...result].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === 'string' && typeof bv === 'string') return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
    return result;
  }, [rows, filterTicker, sortKey, sortAsc]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const SortIcon = ({ col }: { col: SortKey }) => {
    if (sortKey !== col) return <ArrowUpDown size={12} className="text-gray-300" />;
    return sortAsc ? <ArrowUp size={12} /> : <ArrowDown size={12} />;
  };

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex items-center gap-4 flex-wrap">
        <select
          value={filterTicker}
          onChange={(e) => setFilterTicker(e.target.value)}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Tickers</option>
          {tickers.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                period === p ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {p.toUpperCase()}
            </button>
          ))}
        </div>
        {loading && <Loader2 size={16} className="animate-spin text-blue-500" />}
        <span className="text-xs text-gray-400 ml-auto">{filtered.length} rows</span>
      </div>

      {/* Table */}
      {loading && filtered.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 flex flex-col items-center justify-center py-20">
          <Loader2 size={32} className="animate-spin text-blue-500 mb-3" />
          <p className="text-sm text-gray-500">Loading OHLCV data for {tickers.length} tickers...</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  {(['date', 'ticker', 'open', 'high', 'low', 'close', 'volume'] as SortKey[]).map((col) => (
                    <th
                      key={col}
                      onClick={() => handleSort(col)}
                      className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:text-gray-700 select-none"
                    >
                      <div className="flex items-center gap-1">
                        {col} <SortIcon col={col} />
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.map((row, i) => (
                  <tr key={`${row.ticker}-${row.date}-${i}`} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-600 whitespace-nowrap">{row.date}</td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <div
                          className="w-1.5 h-1.5 rounded-full"
                          style={{ backgroundColor: getTickerColor(row.ticker, tickers.indexOf(row.ticker)) }}
                        />
                        <span className="font-medium text-gray-800">{row.ticker}</span>
                      </div>
                    </td>
                    <td className="px-4 py-2 text-gray-700 tabular-nums">{formatPrice(row.open)}</td>
                    <td className="px-4 py-2 text-gray-700 tabular-nums">{formatPrice(row.high)}</td>
                    <td className="px-4 py-2 text-gray-700 tabular-nums">{formatPrice(row.low)}</td>
                    <td className="px-4 py-2 font-medium text-gray-900 tabular-nums">{formatPrice(row.close)}</td>
                    <td className="px-4 py-2 text-gray-600 tabular-nums">{row.volume.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
