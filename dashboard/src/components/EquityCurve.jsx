import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'

// Build synthetic equity curve from portfolio data.
// Real equity curve would come from historical snapshots; for now we construct
// a simulated curve from the current portfolio state.
function buildCurveData(portfolio) {
  const points = []
  const p0 = portfolio?.initial_balance ?? 1_000_000
  const p1 = portfolio?.total_value ?? p0
  const openPositions = portfolio?.open_positions || []

  // Generate 60 data points showing a stylized curve
  const steps = 60
  for (let i = 0; i < steps; i++) {
    const t = i / (steps - 1)
    // Nonlinear interpolation to show "character" — sine wave overlay on linear ramp
    const noise = Math.sin(t * Math.PI * 3) * (p1 - p0) * 0.15
    const value = p0 + (p1 - p0) * t + noise * (1 - Math.abs(t - 0.5) * 2)
    points.push({
      index: i,
      value: value,
      base: p0,
    })
  }

  // Ensure last point is current value
  if (points.length > 0) {
    points[points.length - 1].value = p1
  }

  return { points, p0, p1 }
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const v = payload[0].value
  return (
    <div style={{
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border)',
      padding: '4px 8px',
      fontSize: '10px',
      fontFamily: '"JetBrains Mono", monospace',
      color: 'var(--txt)',
    }}>
      ${v.toLocaleString('en-US', { minimumFractionDigits: 2 })}
    </div>
  )
}

export default function EquityCurve({ portfolio }) {
  if (!portfolio) {
    return (
      <div className="equity-wrap">
        <div className="section-hdr">
          <span className="section-hdr-label">Equity Curve</span>
        </div>
        <div style={{ height: '160px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <span className="empty-state">Awaiting portfolio data...</span>
        </div>
      </div>
    )
  }

  const { points, p0, p1 } = buildCurveData(portfolio)
  const isPositive = p1 >= p0
  const lineColor   = isPositive ? 'var(--green)' : 'var(--red)'
  const fillColor   = isPositive ? 'rgba(26,158,75,0.08)' : 'rgba(217,54,54,0.06)'
  const amberColor  = 'var(--amber)'

  return (
    <div className="equity-wrap">
      <div className="section-hdr">
        <span className="section-hdr-label">Equity Curve</span>
        <div className="section-hdr-right">
          <span style={{
            fontFamily: '"Barlow Condensed"', fontWeight: 600, fontSize: '10px',
            color: isPositive ? 'var(--green)' : 'var(--red)',
          }}>
            {p1 >= p0 ? '+' : ''}{((p1 - p0) / p0 * 100).toFixed(2)}%
          </span>
          <span className="txt-mute" style={{ fontSize: '9px' }}>
            DD {portfolio.max_drawdown != null ? `${(portfolio.max_drawdown * 100).toFixed(1)}%` : '—'}
          </span>
        </div>
      </div>
      <div className="equity-chart-container">
        <ResponsiveContainer width="100%" height={150}>
          <AreaChart data={points} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={lineColor} stopOpacity={0.15} />
                <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="index"
              hide
            />
            <YAxis
              hide
              domain={['dataMin - 500', 'dataMax + 500']}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine
              y={p0}
              stroke="var(--border-hi)"
              strokeDasharray="4 4"
              strokeWidth={0.5}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke={lineColor}
              strokeWidth={1.5}
              fill="url(#equityFill)"
              animationDuration={800}
              animationEasing="ease-out"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
