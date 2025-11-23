import { clsx } from 'clsx';
import React from 'react';

type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' | 'danger' };

export const Button: React.FC<Props> = ({ className, variant = 'primary', ...props }) => (
  <button
    className={clsx(
      'inline-flex items-center justify-center rounded-lg border px-3 py-1.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300/70 disabled:cursor-not-allowed disabled:opacity-50',
      variant === 'primary' && 'border-blue-600 bg-blue-600 text-white hover:bg-blue-700',
      variant === 'ghost' && 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50',
      variant === 'danger' && 'border-rose-600 bg-rose-600 text-white hover:bg-rose-700',
      className,
    )}
    {...props}
  />
);
