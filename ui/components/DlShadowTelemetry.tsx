import React from 'react';
import { Card, CardBody, CardTitle } from './ui/Card';
import { asNYTime, fromNow } from '../lib/time';

type TopShadowEvent = {
  route_id?: string;
  stop_id?: string;
  stop_name?: string;
  dl_error?: number;
  online_score?: number;
};

type DlTelemetry = {
  status?: 'available' | 'unavailable' | 'error';
  model?: string;
  device?: string;
  samples_used?: number;
  train_epochs?: number;
  loss_last?: number;
  recon_error_p90?: number;
  recon_error_p99?: number;
  shadow_alerts_high?: number;
  corr_with_online_score?: number;
  last_run_utc?: string;
  top_shadow_events?: TopShadowEvent[];
};

export const DlShadowTelemetry: React.FC<{ telemetry?: DlTelemetry }> = ({ telemetry }) => {
  const status = telemetry?.status || 'unavailable';
  const tone =
    status === 'available'
      ? 'border-violet-200 bg-violet-50 text-violet-700'
      : status === 'error'
        ? 'border-rose-200 bg-rose-50 text-rose-700'
        : 'border-slate-200 bg-slate-50 text-slate-600';

  const topEvents = Array.isArray(telemetry?.top_shadow_events) ? telemetry?.top_shadow_events.slice(0, 3) : [];

  return (
    <Card>
      <CardBody className="p-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle>DL Shadow (PyTorch)</CardTitle>
          <span className={`rounded-md border px-2 py-0.5 text-[11px] uppercase tracking-wider ${tone}`}>{status}</span>
        </div>

        <div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-xs text-slate-600">
          <div>Model</div>
          <div className="text-right font-medium text-slate-900">{telemetry?.model || '—'}</div>

          <div>Device</div>
          <div className="text-right font-medium text-slate-900">{telemetry?.device || '—'}</div>

          <div>Samples</div>
          <div className="text-right font-medium text-slate-900">{telemetry?.samples_used ?? 0}</div>

          <div>Epochs</div>
          <div className="text-right font-medium text-slate-900">{telemetry?.train_epochs ?? 0}</div>

          <div>Loss</div>
          <div className="text-right font-medium text-slate-900">{(telemetry?.loss_last ?? 0).toFixed(4)}</div>

          <div>Recon P90</div>
          <div className="text-right font-medium text-slate-900">{(telemetry?.recon_error_p90 ?? 0).toFixed(4)}</div>

          <div>Recon P99</div>
          <div className="text-right font-medium text-slate-900">{(telemetry?.recon_error_p99 ?? 0).toFixed(4)}</div>

          <div>High Alerts</div>
          <div className="text-right font-medium text-violet-700">{telemetry?.shadow_alerts_high ?? 0}</div>

          <div>Corr vs Online</div>
          <div className="text-right font-medium text-slate-900">{(telemetry?.corr_with_online_score ?? 0).toFixed(3)}</div>
        </div>

        {topEvents.length > 0 && (
          <div className="mt-2 border-t border-slate-200 pt-2">
            <div className="mb-1 text-[11px] uppercase tracking-[0.14em] text-slate-500">Top DL events</div>
            <div className="space-y-1 text-xs">
              {topEvents.map((ev, idx) => (
                <div key={`${ev.stop_id || 'x'}-${idx}`} className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-slate-700">
                  <div className="font-medium">{ev.route_id || '—'} · {ev.stop_name || ev.stop_id || '—'}</div>
                  <div className="text-slate-500">DL {Number(ev.dl_error || 0).toFixed(4)} | Online {Number(ev.online_score || 0).toFixed(2)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="mt-2 border-t border-slate-200 pt-2 text-[11px] text-slate-500">
          Last run: {telemetry?.last_run_utc ? `${asNYTime(telemetry.last_run_utc)} (${fromNow(telemetry.last_run_utc)})` : '—'}
        </div>
      </CardBody>
    </Card>
  );
};
