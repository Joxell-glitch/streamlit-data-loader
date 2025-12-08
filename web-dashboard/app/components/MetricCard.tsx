interface Props {
  label: string;
  value: string;
  emphasis?: 'positive' | 'negative' | 'neutral';
}

export function MetricCard({ label, value, emphasis = 'neutral' }: Props) {
  const color = emphasis === 'positive' ? 'var(--positive)' : emphasis === 'negative' ? 'var(--negative)' : 'var(--text)';
  return (
    <div className="panel">
      <div className="metric-label">{label}</div>
      <div className="metric-value" style={{ color }}>{value}</div>
    </div>
  );
}
