import React from 'react';

type Props = { checked: boolean; onChange: (v: boolean) => void };

export const Switch: React.FC<Props> = ({ checked, onChange }) => (
  <label className="inline-flex cursor-pointer items-center">
    <input
      type="checkbox"
      className="peer sr-only"
      checked={checked}
      onChange={(e) => onChange(e.target.checked)}
    />
    <div className="relative h-5 w-10 rounded-full border border-slate-300 bg-slate-200 transition peer-checked:border-blue-500 peer-checked:bg-blue-500">
      <div className="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition peer-checked:translate-x-5" />
    </div>
  </label>
);
