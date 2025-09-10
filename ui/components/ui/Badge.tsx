import { clsx } from 'clsx';
import React from 'react';

type Props = React.HTMLAttributes<HTMLSpanElement> & { color?: 'gray' | 'green' | 'amber' | 'orange' | 'red' };

export const Badge: React.FC<Props> = ({ className, color = 'gray', ...props }) => (
  <span
    className={clsx(
      'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
      color === 'gray' && 'bg-gray-100 text-gray-700',
      color === 'green' && 'bg-green-100 text-green-700',
      color === 'amber' && 'bg-amber-100 text-amber-700',
      color === 'orange' && 'bg-orange-100 text-orange-700',
      color === 'red' && 'bg-red-100 text-red-700',
      className
    )}
    {...props}
  />
);

