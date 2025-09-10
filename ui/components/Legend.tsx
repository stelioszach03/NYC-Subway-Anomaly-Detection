import React from 'react';
import { Badge } from './ui/Badge';

const items = [
  { color: '#7dd3fc', label: '0.0 – 0.4' },
  { color: '#fbbf24', label: '0.4 – 0.6' },
  { color: '#fb923c', label: '0.6 – 0.85' },
  { color: '#ef4444', label: '> 0.85' },
];

export const Legend: React.FC = () => (
  <div className="flex flex-col gap-2">
    <div className="text-xs uppercase tracking-wide text-gray-500">Anomaly Scale</div>
    <div className="grid grid-cols-2 gap-2">
      {items.map((i) => (
        <div key={i.label} className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-full" style={{ backgroundColor: i.color }} />
          <span className="text-sm text-gray-700">{i.label}</span>
        </div>
      ))}
    </div>
  </div>
);

