import React from 'react';

type Option = { label: string; value: string };
type Props = {
  value: string;
  onChange: (v: string) => void;
  options: Option[];
};

export const Select: React.FC<Props> = ({ value, onChange, options }) => (
  <select
    className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800 shadow-sm outline-none transition hover:border-slate-400 focus:border-blue-500"
    value={value}
    onChange={(e) => onChange(e.target.value)}
  >
    {options.map((o) => (
      <option key={o.value} value={o.value}>
        {o.label}
      </option>
    ))}
  </select>
);
