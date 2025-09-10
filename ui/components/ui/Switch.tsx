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
    <div className="h-5 w-9 rounded-full bg-gray-300 peer-checked:bg-blue-600 relative transition">
      <div className="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition peer-checked:translate-x-4" />
    </div>
  </label>
);

