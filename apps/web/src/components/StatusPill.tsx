import type { ReactNode } from 'react';

export type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'brand';

export function StatusPill({
  tone = 'neutral',
  children,
  dot = true,
  className = '',
}: {
  tone?: StatusTone;
  children: ReactNode;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span className={`status-pill status-${tone} ${className}`.trim()}>
      {dot && <span className="status-dot" aria-hidden="true" />}
      {children}
    </span>
  );
}
