import React from 'react';

export type IndicatorStatus = 'ok' | 'error' | 'unknown';

const COLOR_MAP: Record<IndicatorStatus, string> = {
  ok: 'var(--positive)',
  error: 'var(--negative)',
  unknown: 'var(--muted)'
};

export function StatusIndicator({
  label,
  status,
  description
}: {
  label: string;
  status: IndicatorStatus;
  description?: string;
}) {
  return (
    <div className="status-indicator">
      <span
        className="status-dot"
        style={{ backgroundColor: COLOR_MAP[status] }}
        aria-hidden
      />
      <div>
        <div className="status-label">{label}</div>
        {description && <div className="status-description">{description}</div>}
      </div>
    </div>
  );
}
