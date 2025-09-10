import React from 'react';

export const Skeleton: React.FC<{ className?: string }> = ({ className }) => (
  <div className={"animate-pulse rounded-lg bg-gray-200 " + (className || '')} />
);

