import { clsx } from 'clsx';
import React from 'react';

type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' };

export const Button: React.FC<Props> = ({ className, variant = 'primary', ...props }) => (
  <button
    className={clsx(
      'inline-flex items-center justify-center rounded-lg px-3 py-2 text-sm font-medium transition shadow',
      variant === 'primary' && 'bg-blue-600 text-white hover:bg-blue-700',
      variant === 'ghost' && 'bg-transparent hover:bg-gray-100',
      className
    )}
    {...props}
  />
);

