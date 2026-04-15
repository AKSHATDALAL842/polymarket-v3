import usePolling from '../hooks/usePolling.js'

const API = '/api'

function fmt(n) {
  if (n == null) return '—'
  return '$' + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtPnl(n) {
  if (n == null) return '—'
  return (n >= 0 ? '+$' : '-$') + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function pnlColor(n) {
  if (n > 0) return 'var(--green)'
  if (n < 0) return 'var(--red)'
  return 'var(--txt-sub)'
}

function pnlClass(n) {
  if (n > 0) return 'positive'
  if (n < 0) return 'negative'
  return 'neutral'
}

export default function VirtualMoney() {
  const { data: p } = usePolling(`${API}/portfolio`, 5000)

  if (!p) {
    return (
      <div className="vm-wrap" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <div className="empty-state">Connecting to portfolio API...</div>
      </div>
    )
  }

  const totalPnl   = (p.unrealized_pnl || 0) + (p.realized_pnl || 0)
  const returnSign = (p.total_return_pct || 0) >= 0 ? '+' : ''
  const openList   = p.open_positions   || []
  const closedList = p.closed_positions || []
  const cats       = p.by_category ? Object.entries(p.by_category) : []

  return (
    <div className="vm-wrap">

      {/* ── Hero ── */}
      <div className="vm-hero">
        <div className="vm-hero-main">
          <div className="vm-hero-eyebrow">Virtual Portfolio · Paper Trading</div>
          <div className="vm-hero-value">{fmt(p.total_value)}</div>
          <div className="vm-hero-sub">
            Started with {fmt(p.initial_balance)} ·{' '}
            <span
              className="vm-hero-return"
              style={{ color: pnlColor(p.total_return_pct) }}
            >
              {returnSign}{(p.total_return_pct || 0).toFixed(2)}% total return
            </span>
          </div>
        </div>

        <div className="vm-stat-strip">
          <div className="vm-stat-item">
            <span className="vm-stat-label">Win Rate</span>
            <span className="vm-stat-value" style={{ color: p.win_rate >= 0.5 ? 'var(--green)' : p.win_rate > 0 ? 'var(--red)' : 'var(--txt-sub)' }}>
              {p.win_rate > 0 ? `${(p.win_rate * 100).toFixed(1)}%` : '—'}
            </span>
            <div className="vm-stat-bar-wrap">
              <div className="vm-stat-bar" style={{
                width: `${(p.win_rate || 0) * 100}%`,
                background: p.win_rate >= 0.5 ? 'var(--green)' : 'var(--red)'
              }} />
            </div>
          </div>

          <div className="vm-stat-item">
            <span className="vm-stat-label">Sharpe</span>
            <span className="vm-stat-value" style={{
              color: p.sharpe_ratio > 1 ? 'var(--green)' : p.sharpe_ratio > 0 ? 'var(--amber)' : p.sharpe_ratio != null ? 'var(--red)' : 'var(--txt-sub)'
            }}>
              {p.sharpe_ratio != null ? p.sharpe_ratio.toFixed(2) : '—'}
            </span>
          </div>

          <div className="vm-stat-item">
            <span className="vm-stat-label">Max Drawdown</span>
            <span className="vm-stat-value" style={{
              color: p.max_drawdown > 0.1 ? 'var(--red)' : p.max_drawdown > 0.05 ? 'var(--amber)' : 'var(--green)'
            }}>
              {p.max_drawdown > 0 ? `-${(p.max_drawdown * 100).toFixed(2)}%` : '0.00%'}
            </span>
            <div className="vm-stat-bar-wrap">
              <div className="vm-stat-bar" style={{
                width: `${Math.min((p.max_drawdown || 0) * 100 * 5, 100)}%`,
                background: p.max_drawdown > 0.1 ? 'var(--red)' : 'var(--amber)'
              }} />
            </div>
          </div>

          <div className="vm-stat-item">
            <span className="vm-stat-label">Open Positions</span>
            <span className="vm-stat-value" style={{ color: openList.length > 0 ? 'var(--amber)' : 'var(--txt-sub)' }}>
              {openList.length}
            </span>
          </div>

          <div className="vm-stat-item">
            <span className="vm-stat-label">Cash Balance</span>
            <span className="vm-stat-value" style={{ color: 'var(--txt)' }}>
              {fmt(p.balance)}
            </span>
          </div>
        </div>
      </div>

      {/* ── P&L strip ── */}
      <div className="vm-pnl-row">
        {[
          { label: 'Unrealized P&L', value: p.unrealized_pnl },
          { label: 'Realized P&L',   value: p.realized_pnl },
          { label: 'Total P&L',      value: totalPnl },
          { label: 'Daily P&L',      value: p.daily_pnl ?? null },
        ].map(({ label, value }) => (
          <div key={label} className={`vm-pnl-card ${pnlClass(value)}`}>
            <span className="vm-pnl-label">{label}</span>
            <span className="vm-pnl-value" style={{ color: pnlColor(value) }}>
              {fmtPnl(value)}
            </span>
          </div>
        ))}
      </div>

      {/* ── Body ── */}
      <div className="vm-body">

        {/* Open Positions */}
        <div className="vm-section">
          <div className="vm-section-header">
            <span className="vm-section-title">Open Positions</span>
            <span className="vm-section-badge">{openList.length}</span>
          </div>
          {openList.length === 0 ? (
            <div className="vm-empty">No open positions — waiting for signals</div>
          ) : (
            <div className="vm-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ minWidth: 260 }}>Market</th>
                    <th>Platform</th>
                    <th>Category</th>
                    <th>Side</th>
                    <th>Entry</th>
                    <th>Size</th>
                    <th>Unrealized P&L</th>
                    <th>Opened</th>
                  </tr>
                </thead>
                <tbody>
                  {openList.map((pos, i) => (
                    <tr key={i}>
                      <td style={{ maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--txt)' }}>
                        {pos.market_question}
                      </td>
                      <td>
                        <span className={`status-pill s-${pos.platform === 'kalshi' ? 'filled' : 'dry_run'}`}>
                          {pos.platform}
                        </span>
                      </td>
                      <td>
                        {pos.category
                          ? <span className={`cat-badge cat-${pos.category}`}>{pos.category}</span>
                          : <span style={{ color: 'var(--txt-mute)' }}>—</span>}
                      </td>
                      <td>
                        <span style={{
                          color: pos.side === 'YES' ? 'var(--green)' : 'var(--red)',
                          fontWeight: 700,
                          fontFamily: '"Barlow Condensed"',
                          fontSize: 12,
                          letterSpacing: '0.06em'
                        }}>
                          {pos.side}
                        </span>
                      </td>
                      <td style={{ color: 'var(--txt-sub)' }}>{(pos.entry_price * 100).toFixed(1)}¢</td>
                      <td style={{ color: 'var(--txt)' }}>{fmt(pos.size_usd)}</td>
                      <td style={{ color: pnlColor(pos.unrealized_pnl), fontWeight: 600 }}>
                        {pos.unrealized_pnl != null ? fmtPnl(pos.unrealized_pnl) : '—'}
                      </td>
                      <td style={{ color: 'var(--txt-mute)' }}>
                        {pos.opened_at ? new Date(pos.opened_at).toLocaleTimeString() : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Closed Positions */}
        <div className="vm-section">
          <div className="vm-section-header">
            <span className="vm-section-title">Closed Positions</span>
            <span className="vm-section-badge">{closedList.length}</span>
          </div>
          {closedList.length === 0 ? (
            <div className="vm-empty">No closed positions yet</div>
          ) : (
            <div className="vm-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ minWidth: 240 }}>Market</th>
                    <th>Platform</th>
                    <th>Category</th>
                    <th>Side</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>Size</th>
                    <th>Realized P&L</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {closedList.map((pos, i) => (
                    <tr key={i}>
                      <td style={{ maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--txt)' }}>
                        {pos.market_question}
                      </td>
                      <td>
                        <span className={`status-pill s-${pos.platform === 'kalshi' ? 'filled' : 'dry_run'}`}>
                          {pos.platform}
                        </span>
                      </td>
                      <td>
                        {pos.category
                          ? <span className={`cat-badge cat-${pos.category}`}>{pos.category}</span>
                          : <span style={{ color: 'var(--txt-mute)' }}>—</span>}
                      </td>
                      <td>
                        <span style={{
                          color: pos.side === 'YES' ? 'var(--green)' : 'var(--red)',
                          fontWeight: 700,
                          fontFamily: '"Barlow Condensed"',
                          fontSize: 12,
                          letterSpacing: '0.06em'
                        }}>
                          {pos.side}
                        </span>
                      </td>
                      <td style={{ color: 'var(--txt-sub)' }}>{(pos.entry_price * 100).toFixed(1)}¢</td>
                      <td style={{ color: 'var(--txt-sub)' }}>
                        {pos.exit_price != null ? `${(pos.exit_price * 100).toFixed(1)}¢` : '—'}
                      </td>
                      <td style={{ color: 'var(--txt)' }}>{fmt(pos.size_usd)}</td>
                      <td style={{ color: pnlColor(pos.realized_pnl), fontWeight: 600 }}>
                        {pos.realized_pnl != null ? fmtPnl(pos.realized_pnl) : '—'}
                      </td>
                      <td>
                        <span className={`status-pill ${pos.realized_pnl > 0 ? 's-filled' : pos.realized_pnl < 0 ? 's-rejected' : 's-simulated'}`}>
                          {pos.realized_pnl > 0 ? 'WIN' : pos.realized_pnl < 0 ? 'LOSS' : pos.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* By Category */}
        {cats.length > 0 && (
          <div className="vm-section">
            <div className="vm-section-header">
              <span className="vm-section-title">Performance by Category</span>
              <span className="vm-section-badge">{cats.length}</span>
            </div>
            <div className="vm-cat-grid">
              {cats.map(([cat, data]) => (
                <div key={cat} className="vm-cat-card">
                  <div className="vm-cat-top">
                    <span className={`cat-badge cat-${cat}`}>{cat}</span>
                    <span className="vm-cat-pnl" style={{ color: pnlColor(data.pnl) }}>
                      {fmtPnl(data.pnl)}
                    </span>
                  </div>
                  {data.win_rate != null && (
                    <div className="vm-winbar-wrap">
                      <div className="vm-winbar-fill" style={{
                        width: `${(data.win_rate || 0) * 100}%`,
                        background: data.win_rate >= 0.5 ? 'var(--green)' : 'var(--red)'
                      }} />
                    </div>
                  )}
                  <div className="vm-cat-meta">
                    <div className="vm-cat-meta-item">
                      <span className="vm-cat-meta-label">Trades</span>
                      <span>{data.trades ?? '—'}</span>
                    </div>
                    <div className="vm-cat-meta-item">
                      <span className="vm-cat-meta-label">Win%</span>
                      <span style={{ color: data.win_rate >= 0.5 ? 'var(--green)' : data.win_rate > 0 ? 'var(--red)' : 'var(--txt-sub)' }}>
                        {data.win_rate != null ? `${(data.win_rate * 100).toFixed(0)}%` : '—'}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
