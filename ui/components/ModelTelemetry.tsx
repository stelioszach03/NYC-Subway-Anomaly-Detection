import React from 'react';
import { Card, CardBody, CardTitle } from './ui/Card';
import { asNYTime, fromNow } from '../lib/time';

type Telemetry = {
  status?: 'available' | 'unavailable' | 'error';
  rows_seen?: number;
  rows_updated?: number;
  drift_events?: number;
  mae_ema?: number;
  residual_q90?: number;
  residual_q99?: number;
  last_batch_processed?: number;
  unscored_backlog?: number;
  last_run_utc?: string;
};

export const ModelTelemetry: React.FC<{ telemetry?: Telemetry }> = ({ telemetry }) => {
  const status = telemetry?.status || 'unavailable';
  const tone =
    status === 'available'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
      : status === 'error'
        ? 'border-rose-200 bg-rose-50 text-rose-700'
        : 'border-slate-200 bg-slate-50 text-slate-600';

  const backlog = telemetry?.unscored_backlog ?? 0;
  const backlogTone = backlog > 5000 ? 'text-amber-700' : 'text-slate-900';

  return (
    <Card>
      <CardBody className="p-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle>Online Model</CardTitle>
          <span className={`rounded-md border px-2 py-0.5 text-[11px] uppercase tracking-wider ${tone}`}>{status}</span>
        </div>

        <div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-xs text-slate-600">
          <div>Rows Seen</div>
          <div className="text-right font-medium text-slate-900">{telemetry?.rows_seen ?? 0}</div>

          <div>Rows Scored</div>
          <div className="text-right font-medium text-slate-900">{telemetry?.rows_updated ?? 0}</div>

          <div>Last Batch</div>
          <div className="text-right font-medium text-slate-900">{telemetry?.last_batch_processed ?? 0}</div>

          <div>Backlog</div>
          <div className={`text-right font-medium ${backlogTone}`}>{backlog}</div>

          <div>Drift Events</div>
          <div className="text-right font-medium text-slate-900">{telemetry?.drift_events ?? 0}</div>

          <div>MAE (EMA)</div>
          <div className="text-right font-medium text-slate-900">{(telemetry?.mae_ema ?? 0).toFixed(1)}</div>

          <div>Residual Q90</div>
          <div className="text-right font-medium text-slate-900">{(telemetry?.residual_q90 ?? 0).toFixed(1)}</div>

          <div>Residual Q99</div>
          <div className="text-right font-medium text-slate-900">{(telemetry?.residual_q99 ?? 0).toFixed(1)}</div>
        </div>

        <div className="mt-2 border-t border-slate-200 pt-2 text-[11px] text-slate-500">
          Last run: {telemetry?.last_run_utc ? `${asNYTime(telemetry.last_run_utc)} (${fromNow(telemetry.last_run_utc)})` : '—'}
        </div>
      </CardBody>
    </Card>
  );
};
