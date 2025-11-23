import React, { useEffect, useMemo, useState } from 'react';
import { Badge } from './ui/Badge';
import { scoreBand, scoreToColor, scoreToTextColor } from '../lib/utils';
import { formatNYFromEpoch, fromNowEpoch } from '../lib/time';
import { withBasePath } from '../lib/basePath';

type Row = {
  observed_ts_epoch_ms?: number;
  event_ts_epoch_ms?: number | null;
  route_id: string;
  stop_id: string;
  stop_name?: string;
  headway_sec?: number;
  predicted_headway_sec?: number;
  anomaly_score?: number;
  residual?: number;
};

type Props = {
  route: string;
  tickMs?: number;
};

export const AnomalyTable: React.FC<Props> = ({ route, tickMs }) => {
  const [rows, setRows] = useState<Row[]>([]);
  const [page, setPage] = useState(1);
  const pageSize = 20;

  useEffect(() => {
    setPage(1);
  }, [route]);

  useEffect(() => {
    let aborted = false;
    let inFlight = false;
    const ctrl = new AbortController();
    let interval: ReturnType<typeof setInterval> | undefined;

    const run = async () => {
      if (inFlight) return;
      if (typeof document !== 'undefined' && document.hidden) return;
      inFlight = true;
      try {
        const url = new URL(withBasePath('/api/anomalies'), window.location.origin);
        url.searchParams.set('window', '15m');
        url.searchParams.set('route_id', route || 'All');
        url.searchParams.set('limit', '400');
        const r = await fetch(url.toString(), { signal: ctrl.signal });
        if (!r.ok) return;
        const data = (await r.json()) as Row[];
        if (!aborted) setRows(Array.isArray(data) ? data : []);
      } catch {
        // no-op
      } finally {
        inFlight = false;
      }
    };

    run();
    if (tickMs && tickMs > 0) interval = setInterval(run, tickMs);

    return () => {
      aborted = true;
      ctrl.abort();
      if (interval) clearInterval(interval);
    };
  }, [route, tickMs]);

  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const currentPage = Math.min(page, totalPages);

  const paged = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return rows.slice(start, start + pageSize);
  }, [rows, currentPage]);

  const onRowClick = (row: Row) => {
    window.dispatchEvent(new CustomEvent('focusStopId', { detail: row.stop_id }));
  };

  return (
    <div className="h-full min-h-0 rounded-xl border border-slate-200 bg-white p-2 shadow-sm">
      <div className="mb-2 flex items-center justify-between px-1">
        <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Top anomalies</div>
        <div className="text-xs text-slate-500">{rows.length} rows</div>
      </div>

      <div className="h-[calc(100%-62px)] overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-sm text-slate-800">
          <thead className="sticky top-0 bg-slate-50 text-xs text-slate-600">
            <tr>
              <th className="px-2 py-2 text-left font-medium">Observed (NYC)</th>
              <th className="px-2 py-2 text-left font-medium">Route</th>
              <th className="px-2 py-2 text-left font-medium">Stop</th>
              <th className="px-2 py-2 text-left font-medium">Headway</th>
              <th className="px-2 py-2 text-left font-medium">Score</th>
              <th className="px-2 py-2 text-left font-medium">Residual</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((r, idx) => {
              const score = Number(r.anomaly_score ?? 0);
              const band = scoreBand(score);
              const bg = scoreToColor(score);
              const fg = scoreToTextColor(score);
              return (
                <tr
                  key={`${r.stop_id}-${idx}`}
                  className="cursor-pointer border-t border-slate-100 bg-white hover:bg-slate-50"
                  onClick={() => onRowClick(r)}
                >
                  <td className="px-2 py-1.5 align-top">
                    <div>{r.observed_ts_epoch_ms ? formatNYFromEpoch(r.observed_ts_epoch_ms) : '—'}</div>
                    <div className="text-xs text-slate-500">
                      {r.observed_ts_epoch_ms ? fromNowEpoch(r.observed_ts_epoch_ms) : ''}
                    </div>
                    {r.event_ts_epoch_ms ? (
                      <div className="text-xs text-slate-400">ETA: {formatNYFromEpoch(r.event_ts_epoch_ms)}</div>
                    ) : null}
                  </td>
                  <td className="px-2 py-1.5 align-top font-semibold text-blue-700">{r.route_id}</td>
                  <td className="px-2 py-1.5 align-top">{r.stop_name || r.stop_id}</td>
                  <td className="px-2 py-1.5 align-top">
                    <div>{typeof r.headway_sec === 'number' ? `${r.headway_sec.toFixed(0)}s` : '—'}</div>
                    {typeof r.predicted_headway_sec === 'number' ? (
                      <div className="text-xs text-slate-500">pred {r.predicted_headway_sec.toFixed(0)}s</div>
                    ) : null}
                  </td>
                  <td className="px-2 py-1.5 align-top">
                    <div className="flex items-center gap-2">
                      <Badge style={{ backgroundColor: bg, color: fg }}>
                        {score.toFixed(2)}
                      </Badge>
                      <span className="text-xs text-slate-500">{band.tone}</span>
                    </div>
                  </td>
                  <td className="px-2 py-1.5 align-top">{(r.residual ?? 0).toFixed(0)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        <button className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50" disabled={currentPage <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
          Prev
        </button>
        <div>
          Page {currentPage}/{totalPages}
        </div>
        <button
          className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50"
          disabled={currentPage >= totalPages}
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
        >
          Next
        </button>
      </div>
    </div>
  );
};
