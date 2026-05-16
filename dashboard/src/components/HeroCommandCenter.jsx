import { motion, AnimatePresence } from 'framer-motion'

function formatUSD(n) {
  if (n == null) return '—'
  return '$' + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatPct(n) {
  if (n == null) return '—'
  return (n * 100).toFixed(1) + '%'
}

function trendIndicator(current, previous) {
  if (current == null || previous == null) return null
  if (current > previous) return { symbol: '▲', color: 'var(--green)' }
  if (current < previous) return { symbol: '▼', color: 'var(--red)' }
  return { symbol: '◆', color: 'var(--txt-sub)' }
}

function HeroCard({ label, value, sub, color, trend }) {
  return (
    <div className="hero-card">
      <span className="hero-label">{label}</span>
      <AnimatePresence mode="wait">
        <motion.span
          key={value}
          className="hero-value"
          style={{ color: color || 'var(--txt)' }}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
        >
          {value ?? '—'}
        </motion.span>
      </AnimatePresence>
      <span className="hero-sub">
        {trend && (
          <span className="hero-trend" style={{ color: trend.color }}>{trend.symbol}</span>
        )}
        {sub && <span>{sub}</span>}
      </span>
    </div>
  )
}

export default function HeroCommandCenter({ portfolio, stats, status, markets }) {
  const trades = stats?.trades || {}
  const cal    = stats?.calibration || {}
  const lat    = stats?.latency || {}
  const risk   = status?.risk || {}

  const totalValue   = portfolio?.total_value
  const dailyPnl     = trades.total_pnl
  const winRate      = trades.total > 0
    ? (trades.wins / (trades.wins + trades.losses || 1))
    : null
  const accuracy     = cal.overall_accuracy
  const p50Latency   = lat.p50
  const activeMarkets = markets?.length ?? (status?.tracked_markets ?? 0)
  const exposure     = risk.total_exposure ?? 0
  const signals      = status?.signals_generated ?? trades.total ?? 0

  return (
    <div className="hero">
      <div className="hero-grid">
        <HeroCard
          label="Total Equity"
          value={formatUSD(totalValue)}
          sub={portfolio?.total_return_pct != null
            ? `${portfolio.total_return_pct >= 0 ? '+' : ''}${portfolio.total_return_pct.toFixed(2)}%`
            : undefined}
          color={totalValue > (portfolio?.initial_balance || 0) ? 'var(--green)' : totalValue < (portfolio?.initial_balance || 0) ? 'var(--red)' : 'var(--amber)'}
        />
        <HeroCard
          label="Daily P&L"
          value={dailyPnl != null ? `${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toFixed(2)}` : '—'}
          color={dailyPnl > 0 ? 'var(--green)' : dailyPnl < 0 ? 'var(--red)' : 'var(--txt)'}
          sub={`${trades.pending ?? 0} pending`}
        />
        <HeroCard
          label="Signal Accuracy"
          value={accuracy != null ? formatPct(accuracy) : '—'}
          color={accuracy > 0.6 ? 'var(--green)' : accuracy > 0 ? 'var(--amber)' : undefined}
          sub={winRate != null ? `WR ${formatPct(winRate)}` : undefined}
        />
        <HeroCard
          label="Fill Latency"
          value={p50Latency != null ? `${p50Latency}ms` : '—'}
          color={p50Latency < 1000 ? 'var(--green)' : p50Latency < 3000 ? 'var(--amber)' : 'var(--red)'}
          sub={lat.p95 != null ? `p95 ${lat.p95}ms` : undefined}
        />
        <HeroCard
          label="Risk Exposure"
          value={formatUSD(exposure)}
          color={exposure > 200 ? 'var(--red)' : exposure > 100 ? 'var(--amber)' : 'var(--txt)'}
          sub={`${risk.open_positions ?? 0} positions`}
        />
        <HeroCard
          label="Active Mkts"
          value={activeMarkets}
          sub={`${signals} signals`}
          color={signals > 0 ? 'var(--amber)' : undefined}
        />
      </div>
    </div>
  )
}
