import React from 'react';
import { SCORE_BANDS } from '../lib/utils';

export const Legend: React.FC = () => (
  <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
    <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Anomaly Scale</div>
    <div className="mt-2 grid grid-cols-1 gap-2 text-xs">
      {SCORE_BANDS.map((band) => (
        <div key={band.id} className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: band.color }} />
            <span className="font-medium text-slate-700">{band.label}</span>
          </div>
          <span className="text-slate-500">{band.tone}</span>
        </div>
      ))}
    </div>
  </div>
);
