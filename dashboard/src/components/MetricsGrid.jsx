function MetricCard({ label, value, sub, color, dim }) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-value" style={{ color: color || 'var(--txt)', opacity: dim ? 0.4 : 1 }}>
        {value ?? <span style={{ opacity: 0.3, fontSize: '14px' }}>—</span>}
      </div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  )
}

function pct(n) { return n != null ? (n * 100).toFixed(1) + '%' : null }
function fmtMs(n) { return n != null ? n + 'ms' : null }
function fmtF2(n) { return n != null ? Number(n).toFixed(2) : null }

export default function MetricsGrid({ stats, status }) {
  const trades = stats?.trades || {}
  const cal    = stats?.calibration || {}
  const lat    = stats?.latency || {}

  const winRate = trades.total > 0
    ? pct(trades.wins / (trades.wins + trades.losses || 1))
    : null

  const pnlColor = trades.total_pnl > 0 ? 'var(--green)'
    : trades.total_pnl < 0 ? 'var(--red)' : undefined

  return (
    <div className="metrics-grid">
      <MetricCard
        label="Win Rate"
        value={winRate}
        sub={`${trades.wins ?? 0}W / ${trades.losses ?? 0}L`}
        color={winRate ? (parseFloat(winRate) > 50 ? 'var(--green)' : 'var(--red)') : undefined}
      />
      <MetricCard
        label="Avg EV"
        value={trades.avg_ev != null ? ((trades.avg_ev > 0 ? '+' : '') + pct(trades.avg_ev)) : null}
        sub={`${trades.total ?? 0} trades`}
        color={trades.avg_ev > 0 ? 'var(--amber)' : undefined}
      />
      <MetricCard
        label="Daily P&L"
        value={trades.total_pnl != null ? `$${trades.total_pnl?.toFixed(2)}` : null}
        sub={`${trades.pending ?? 0} pending`}
        color={pnlColor}
      />
      <MetricCard
        label="Accuracy"
        value={pct(cal.overall_accuracy)}
        sub={`Brier ${fmtF2(cal.brier_score) ?? '—'}`}
        color={cal.overall_accuracy > 0.6 ? 'var(--green)' : cal.overall_accuracy > 0 ? 'var(--amber)' : undefined}
      />
      <MetricCard
        label="P50 Latency"
        value={fmtMs(lat.p50)}
        sub={`p95: ${fmtMs(lat.p95) ?? '—'}`}
        color={lat.p50 < 1000 ? 'var(--green)' : lat.p50 < 3000 ? 'var(--amber)' : 'var(--red)'}
      />
      <MetricCard
        label="ECE"
        value={fmtF2(cal.ece)}
        sub="Calibration error"
        color={cal.ece < 0.05 ? 'var(--green)' : cal.ece < 0.15 ? 'var(--amber)' : 'var(--red)'}
      />
    </div>
  )
}
