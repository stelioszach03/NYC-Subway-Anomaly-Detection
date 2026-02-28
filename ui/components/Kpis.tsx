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
  last_updated_epoch_ms?: number;
};

export const Kpis: React.FC<{ summary?: Summary }> = ({ summary }) => {
  const s = summary;
  const updatedEpoch = s?.last_updated_epoch_ms;
  return (
    <div className="grid grid-cols-2 gap-4">
      <Card>
        <CardBody>
          <CardTitle>Stations</CardTitle>
          <div className="text-2xl font-semibold">{s?.stations_total ?? 0}</div>
        </CardBody>
      </Card>
      <Card>
        <CardBody>
          <CardTitle>Active trains</CardTitle>
          <div className="text-2xl font-semibold">{s?.trains_active ?? 0}</div>
        </CardBody>
      </Card>
      <Card>
        <CardBody>
          <CardTitle>Anomalies ({s?.window ?? '15m'})</CardTitle>
          <div className="text-2xl font-semibold flex items-end gap-2">
            <span>{s?.anomalies_count ?? 0}</span>
            <span className="text-xs text-gray-500 mb-1">{(s?.anomaly_rate_perc ?? 0).toFixed(2)}%</span>
          </div>
        </CardBody>
      </Card>
      <Card>
        <CardBody>
          <CardTitle>High severity</CardTitle>
          <div className="text-2xl font-semibold">{s?.anomalies_high ?? 0}</div>
        </CardBody>
      </Card>
      <Card>
        <CardBody>
          <CardTitle>Last data update</CardTitle>
          <div className="text-sm font-medium">{formatNYFromEpoch(updatedEpoch)}</div>
          <div className="text-xs text-gray-500">{fromNowEpoch(updatedEpoch)}</div>
        </CardBody>
      </Card>
    </div>
  );
};
