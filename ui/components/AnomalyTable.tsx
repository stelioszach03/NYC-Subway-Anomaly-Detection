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

const SNAPSHOT_ROWS: Row[] = [
  {
    observed_ts_epoch_ms: 1772383169000,
    event_ts_epoch_ms: 1772383229000,
    route_id: 'L',
    stop_id: 'L14S',
    stop_name: '14 St - Union Sq',
    headway_sec: 512,
    predicted_headway_sec: 302,
    anomaly_score: 0.91,
    residual: 184,
  },
  {
    observed_ts_epoch_ms: 1772383091000,
    event_ts_epoch_ms: 1772383151000,
    route_id: 'N',
    stop_id: 'N57S',
    stop_name: '57 St - 7 Av',
    headway_sec: 476,
    predicted_headway_sec: 319,
    anomaly_score: 0.87,
    residual: 151,
  },
  {
    observed_ts_epoch_ms: 1772383040000,
    event_ts_epoch_ms: 1772383100000,
    route_id: 'A',
    stop_id: 'A34S',
    stop_name: 'Fulton St',
    headway_sec: 428,
    predicted_headway_sec: 343,
    anomaly_score: 0.74,
    residual: 96,
  },
];

export const AnomalyTable: React.FC<Props> = ({ route, tickMs }) => {
  const [rows, setRows] = useState<Row[]>(SNAPSHOT_ROWS);
  const [page, setPage] = useState(1);
  const [hydrated, setHydrated] = useState(false);
  const pageSize = 20;

  useEffect(() => {
    setHydrated(true);
  }, []);

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

  const tableStats = useMemo(() => {
    const scores = rows
      .map((row) => Number(row.anomaly_score ?? 0))
      .filter((value) => Number.isFinite(value))
      .sort((a, b) => a - b);

    const percentile = (ratio: number) => {
      if (scores.length === 0) return 0;
      const idx = Math.min(scores.length - 1, Math.max(0, Math.round((scores.length - 1) * ratio)));
      return scores[idx];
    };

    return {
      exactOne: scores.filter((value) => value >= 0.9995).length,
      critical: scores.filter((value) => value >= 0.85).length,
      p50: percentile(0.5),
    };
  }, [rows]);

  const onRowClick = (row: Row) => {
    window.dispatchEvent(new CustomEvent('focusStopId', { detail: row.stop_id }));
  };

  return (
    <div className="flex h-full min-h-0 flex-col rounded-xl border border-slate-200 bg-white p-2 shadow-sm">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 px-1">
        <div>
          <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Ranked incidents</div>
          <div className="mt-1 text-xs text-slate-500">
            Sorted by model score. When multiple critical rows hit the same ceiling, use residual and gap context to compare them.
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <Badge color="gray">{rows.length} rows</Badge>
          <Badge color="red">{tableStats.exactOne} exact 1.000</Badge>
          <Badge color="orange">{tableStats.critical} critical</Badge>
          <Badge color="amber">p50 {tableStats.p50.toFixed(3)}</Badge>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-sm text-slate-800">
          <thead className="sticky top-0 bg-slate-50 text-xs text-slate-600">
            <tr>
              <th className="px-2 py-2 text-left font-medium">#</th>
              <th className="px-2 py-2 text-left font-medium">Incident</th>
              <th className="px-2 py-2 text-left font-medium">Observed (NYC)</th>
              <th className="px-2 py-2 text-left font-medium">Gap vs pred</th>
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
              const headway = Number(r.headway_sec ?? 0);
              const predicted = Number(r.predicted_headway_sec ?? 0);
              const delta = Number.isFinite(headway) && Number.isFinite(predicted) ? headway - predicted : 0;
              const ratio = predicted > 0 ? headway / predicted : 0;
              const absoluteResidual = Math.abs(Number(r.residual ?? delta));
              const rank = (currentPage - 1) * pageSize + idx + 1;
              return (
                <tr
                  key={`${r.stop_id}-${idx}`}
                  className="cursor-pointer border-t border-slate-100 bg-white hover:bg-slate-50"
                  onClick={() => onRowClick(r)}
                >
                  <td className="px-2 py-1.5 align-top text-xs font-semibold text-slate-500">#{rank}</td>
                  <td className="px-2 py-1.5 align-top">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex min-w-7 items-center justify-center rounded-md bg-slate-900 px-1.5 py-0.5 text-[11px] font-semibold text-white">
                        {r.route_id}
                      </span>
                      <div className="font-medium text-slate-900">{r.stop_name || r.stop_id}</div>
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500">{r.stop_id}</div>
                  </td>
                  <td className="px-2 py-1.5 align-top">
                    <div>{r.observed_ts_epoch_ms ? formatNYFromEpoch(r.observed_ts_epoch_ms) : '—'}</div>
                    <div className="text-xs text-slate-500">
                      {r.observed_ts_epoch_ms ? (hydrated ? fromNowEpoch(r.observed_ts_epoch_ms) : 'Snapshot row') : ''}
                    </div>
                    {r.event_ts_epoch_ms ? (
                      <div className="text-xs text-slate-400">ETA: {formatNYFromEpoch(r.event_ts_epoch_ms)}</div>
                    ) : null}
                  </td>
                  <td className="px-2 py-1.5 align-top">
                    <div className="font-medium text-slate-900">{typeof r.headway_sec === 'number' ? `${r.headway_sec.toFixed(0)}s` : '—'}</div>
                    {typeof r.predicted_headway_sec === 'number' ? <div className="text-xs text-slate-500">pred {r.predicted_headway_sec.toFixed(0)}s</div> : null}
                    {typeof r.predicted_headway_sec === 'number' ? (
                      <div className={delta >= 0 ? 'text-xs text-rose-600' : 'text-xs text-emerald-600'}>
                        {delta >= 0 ? '+' : ''}
                        {delta.toFixed(0)}s vs model
                        {ratio > 0 ? ` (${ratio.toFixed(2)}x)` : ''}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-2 py-1.5 align-top">
                    <div className="flex items-center gap-2">
                      <Badge style={{ backgroundColor: bg, color: fg }}>
                        {score.toFixed(3)}
                      </Badge>
                      <span className="text-xs text-slate-500">{band.tone}</span>
                      {score >= 0.9995 ? <span className="text-[11px] font-medium text-slate-400">ceiling</span> : null}
                    </div>
                    <div className="mt-1 h-1.5 w-28 overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full rounded-full" style={{ width: `${Math.max(6, score * 100)}%`, backgroundColor: bg }} />
                    </div>
                  </td>
                  <td className="px-2 py-1.5 align-top">
                    <div className={Number(r.residual ?? 0) >= 0 ? 'font-medium text-rose-700' : 'font-medium text-emerald-700'}>
                      {Number(r.residual ?? 0) >= 0 ? '+' : ''}
                      {(r.residual ?? 0).toFixed(0)}s
                    </div>
                    <div className="text-xs text-slate-500">
                      abs {absoluteResidual.toFixed(0)}s
                    </div>
                  </td>
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
