export function MetricBar({
  label,
  value,
  max = 5,
  tone = 'brand',
}: {
  label: string;
  value: number;
  max?: number;
  tone?: 'brand' | 'mint' | 'amber';
}) {
  const ratio = Math.max(0, Math.min(1, value / max));
  return (
    <div className={`metric-bar metric-${tone}`}>
      <div className="metric-bar-head">
        <span>{label}</span>
        <span className="metric-bar-value">{value.toFixed(1)}</span>
      </div>
      <div className="metric-bar-track">
        <span style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}
