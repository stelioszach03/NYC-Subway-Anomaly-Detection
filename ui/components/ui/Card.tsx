import { clsx } from 'clsx';
import React from 'react';

export const Card: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, ...props }) => (
  <div className={clsx('rounded-xl border border-slate-200 bg-white shadow-sm', className)} {...props} />
);

export const CardBody: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, ...props }) => (
  <div className={clsx('p-4', className)} {...props} />
);

export const CardTitle: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, ...props }) => (
  <div className={clsx('text-[11px] uppercase tracking-[0.14em] text-slate-500', className)} {...props} />
);
