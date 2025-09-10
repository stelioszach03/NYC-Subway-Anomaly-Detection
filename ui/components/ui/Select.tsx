import React from 'react';

type Option = { label: string; value: string };
type Props = {
  value: string;
  onChange: (v: string) => void;
  options: Option[];
};

export const Select: React.FC<Props> = ({ value, onChange, options }) => (
  <select
    className="rounded-lg border border-gray-300 bg-white px-2 py-1 text-sm"
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

