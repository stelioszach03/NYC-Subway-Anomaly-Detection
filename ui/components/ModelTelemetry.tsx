import React from 'react';
import { Card, CardBody, CardTitle } from './ui/Card';

type Telemetry = {
  status?: 'available' | 'unavailable' | 'error';
  rows_seen?: number;
  rows_updated?: number;
  drift_events?: number;
  mae_ema?: number;
  last_run_utc?: string;
};

export const ModelTelemetry: React.FC<{ telemetry?: Telemetry }> = ({ telemetry }) => {
  const status = telemetry?.status || 'unavailable';
  const tone =
    status === 'available' ? 'text-green-700 bg-green-50 border-green-200' :
    status === 'error' ? 'text-red-700 bg-red-50 border-red-200' :
    'text-gray-700 bg-gray-50 border-gray-200';

  return (
    <Card>
      <CardBody>
        <div className="flex items-center justify-between">
          <CardTitle>Model telemetry</CardTitle>
          <span className={`text-xs px-2 py-0.5 rounded border ${tone}`}>{status}</span>
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
          <div>Rows seen</div>
          <div className="text-right font-medium">{telemetry?.rows_seen ?? 0}</div>
          <div>Rows scored</div>
          <div className="text-right font-medium">{telemetry?.rows_updated ?? 0}</div>
          <div>Drift events</div>
          <div className="text-right font-medium">{telemetry?.drift_events ?? 0}</div>
          <div>MAE (EMA)</div>
          <div className="text-right font-medium">{(telemetry?.mae_ema ?? 0).toFixed(2)}</div>
        </div>
      </CardBody>
    </Card>
  );
};
