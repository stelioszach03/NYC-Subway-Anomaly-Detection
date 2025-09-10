import React, { useEffect, useMemo, useState } from 'react';
import { Badge } from './ui/Badge';
import { scoreToColor } from '../lib/utils';
import { formatNYFromEpoch, fromNowEpoch } from '../lib/time';

type Row = {
  // Canonical epoch fields
  observed_ts_epoch_ms?: number;
  event_ts_epoch_ms?: number | null;
  // Legacy
  ts?: string;
  ts_epoch_ms?: number;
  route_id: string;
  stop_id: string;
  stop_name?: string;
  anomaly_score?: number;
  residual?: number;
};

export const AnomalyTable: React.FC<{ route: string }> = ({ route }) => {
  const [rows, setRows] = useState<Row[]>([]);
  const [page, setPage] = useState(1);
  const pageSize = 20;

  useEffect(() => {
    let aborted = false;
    const ctrl = new AbortController();
    const run = async () => {
      const url = new URL('/api/anomalies', window.location.origin);
      url.searchParams.set('window', '15m');
      url.searchParams.set('route_id', route || 'All');
      const r = await fetch(url.toString(), { signal: ctrl.signal });
      if (!r.ok) return;
      const data = (await r.json()) as Row[];
      if (!aborted) setRows(data);
    };
    run();
    return () => {
      aborted = true;
      ctrl.abort();
    };
  }, [route]);

  const paged = useMemo(() => {
    const start = (page - 1) * pageSize;
    return rows.slice(start, start + pageSize);
  }, [rows, page]);

  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));

  const onRowClick = (row: Row) => {
    window.dispatchEvent(new CustomEvent('focusStopId', { detail: row.stop_id }));
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-wide text-gray-500">Top anomalies</div>
        <div className="text-xs text-gray-500">{rows.length} rows</div>
      </div>
      <div className="max-h-80 overflow-auto rounded-xl border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              <th className="px-2 py-1 text-left">Observed (NYC)</th>
              <th className="px-2 py-1 text-left">Route</th>
              <th className="px-2 py-1 text-left">Stop</th>
              <th className="px-2 py-1 text-left">Score</th>
              <th className="px-2 py-1 text-left">Residual</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((r, idx) => (
              <tr key={idx} className="hover:bg-gray-50 cursor-pointer" onClick={() => onRowClick(r)}>
                <td className="px-2 py-1">
                  <div>{r.observed_ts_epoch_ms ? formatNYFromEpoch(r.observed_ts_epoch_ms) : '—'}</div>
                  {r.observed_ts_epoch_ms ? (
                    <div className="text-xs text-gray-500">{fromNowEpoch(r.observed_ts_epoch_ms)}</div>
                  ) : (
                    <div className="text-xs text-gray-400">{''}</div>
                  )}
                  {r.event_ts_epoch_ms ? (
                    <div className="text-xs text-gray-400">ETA: {formatNYFromEpoch(r.event_ts_epoch_ms)}</div>
                  ) : null}
                </td>
                <td className="px-2 py-1">{r.route_id}</td>
                <td className="px-2 py-1">{r.stop_name || r.stop_id}</td>
                <td className="px-2 py-1">
                  <Badge style={{ backgroundColor: scoreToColor(r.anomaly_score ?? 0), color: '#111' }}>
                    {(r.anomaly_score ?? 0).toFixed(2)}
                  </Badge>
                </td>
                <td className="px-2 py-1">{(r.residual ?? 0).toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between text-xs text-gray-600">
        <button className="underline" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
          Prev
        </button>
        <div>
          Page {page}/{totalPages}
        </div>
        <button
          className="underline"
          disabled={page >= totalPages}
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
        >
          Next
        </button>
      </div>
    </div>
  );
};
