import React from 'react';
import { Card, CardBody, CardTitle } from './ui/Card';
import { formatNYFromEpoch, fromNowEpoch } from '../lib/time';

type Summary = {
  window: string;
  stations_total: number;
  trains_active: number;
  anomalies_count: number;
  anomalies_high: number;
  anomaly_rate_perc: number;
  scored_rows?: number;
  last_updated_epoch_ms?: number;
};

const fmtInt = (v: number | undefined) => (Number(v || 0)).toLocaleString('en-US');

export const Kpis: React.FC<{ summary?: Summary }> = ({ summary }) => {
  const s = summary;
  const updatedEpoch = s?.last_updated_epoch_ms;

  return (
    <div className="grid grid-cols-2 gap-2">
      <Card>
        <CardBody className="p-3">
          <CardTitle>Stations</CardTitle>
          <div className="mt-1 text-xl font-semibold text-slate-900">{fmtInt(s?.stations_total)}</div>
        </CardBody>
      </Card>

      <Card>
        <CardBody className="p-3">
          <CardTitle>Active Trains</CardTitle>
          <div className="mt-1 text-xl font-semibold text-slate-900">{fmtInt(s?.trains_active)}</div>
        </CardBody>
      </Card>

      <Card>
        <CardBody className="p-3">
          <CardTitle>Anomalies ({s?.window ?? '15m'})</CardTitle>
          <div className="mt-1 flex items-end gap-2 text-xl font-semibold text-amber-700">
            <span>{fmtInt(s?.anomalies_count)}</span>
            <span className="mb-1 text-xs font-medium text-slate-500">{(s?.anomaly_rate_perc ?? 0).toFixed(2)}%</span>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody className="p-3">
          <CardTitle>High Severity</CardTitle>
          <div className="mt-1 text-xl font-semibold text-rose-700">{fmtInt(s?.anomalies_high)}</div>
        </CardBody>
      </Card>

      <Card>
        <CardBody className="p-3">
          <CardTitle>Scored Rows</CardTitle>
          <div className="mt-1 text-xl font-semibold text-blue-700">{fmtInt(s?.scored_rows)}</div>
        </CardBody>
      </Card>

      <Card>
        <CardBody className="p-3">
          <CardTitle>Last Update</CardTitle>
          <div className="mt-1 text-sm font-medium text-slate-900">{formatNYFromEpoch(updatedEpoch)}</div>
          <div className="text-xs text-slate-500">{fromNowEpoch(updatedEpoch)}</div>
        </CardBody>
      </Card>
    </div>
  );
};
