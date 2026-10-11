/** 90-day mini chart (inline SVG, no library). Green when the period ended higher. */
export function Sparkline({ values, width = 90, height = 26 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return <span className="muted">–</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((v, i) => `${((i / (values.length - 1)) * width).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`)
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  const change = ((values[values.length - 1] / values[0] - 1) * 100).toFixed(0);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
      aria-label={`90 dagen: ${up ? "+" : ""}${change}%`}>
      <title>{`90 dagen: ${up ? "+" : ""}${change}%`}</title>
      <polyline points={points} fill="none" stroke={up ? "var(--ok)" : "var(--bad)"} strokeWidth="1.5" />
    </svg>
  );
}
