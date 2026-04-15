import usePolling from '../hooks/usePolling.js'

const API = '/api'

function StatCard({ label, value, color, sub }) {
  return (
    <div className="vm-stat-card">
      <div className="vm-stat-label">{label}</div>
      <div className="vm-stat-value" style={{ color: color || 'var(--txt)' }}>{value}</div>
      {sub && <div className="vm-stat-sub">{sub}</div>}
    </div>
  )
}

function fmt(n, prefix = '$') {
  if (n == null) return '—'
  return `${prefix}${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function fmtPnl(n) {
  if (n == null) return '—'
  const sign = n >= 0 ? '+' : '-'
  return `${sign}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function pnlColor(n) {
  if (n > 0) return 'var(--green)'
  if (n < 0) return 'var(--red)'
  return 'var(--txt)'
}

export default function VirtualMoney() {
  const { data: portfolio } = usePolling(`${API}/portfolio`, 5000)

  if (!portfolio) {
    return (
      <div className="vm-wrap">
        <div className="empty-state" style={{ paddingTop: '60px' }}>Loading virtual portfolio...</div>
      </div>
    )
  }

  const {
    balance, initial_balance, total_value,
    unrealized_pnl, realized_pnl,
    open_positions, closed_positions,
    win_rate, sharpe_ratio, max_drawdown,
    total_return_pct, by_category
  } = portfolio

  const totalPnl = (unrealized_pnl || 0) + (realized_pnl || 0)

  return (
    <div className="vm-wrap">
      {/* ── Header ── */}
      <div className="vm-header">
        <div className="vm-title">Virtual Portfolio</div>
        <div className="vm-balance">
          <span className="vm-balance-label">Total Value</span>
          <span className="vm-balance-value">{fmt(total_value)}</span>
        </div>
      </div>

      {/* ── Top stats ── */}
      <div className="vm-stats-grid">
        <StatCard label="Cash Balance"    value={fmt(balance)}            color="var(--txt)" />
        <StatCard label="Starting Balance" value={fmt(initial_balance)}   color="var(--txt-sub)" />
        <StatCard label="Total Return"
          value={`${total_return_pct >= 0 ? '+' : ''}${(total_return_pct || 0).toFixed(2)}%`}
          color={pnlColor(total_return_pct)} />
        <StatCard label="Unrealized P&L"  value={fmtPnl(unrealized_pnl)} color={pnlColor(unrealized_pnl)} />
        <StatCard label="Realized P&L"    value={fmtPnl(realized_pnl)}   color={pnlColor(realized_pnl)} />
        <StatCard label="Total P&L"       value={fmtPnl(totalPnl)}       color={pnlColor(totalPnl)} />
        <StatCard label="Win Rate"
          value={win_rate > 0 ? `${(win_rate * 100).toFixed(1)}%` : '—'}
          color={win_rate >= 0.5 ? 'var(--green)' : win_rate > 0 ? 'var(--red)' : 'var(--txt-sub)'} />
        <StatCard label="Sharpe Ratio"
          value={sharpe_ratio != null ? sharpe_ratio.toFixed(2) : '—'}
          color={sharpe_ratio > 1 ? 'var(--green)' : sharpe_ratio > 0 ? 'var(--amber)' : 'var(--red)'} />
        <StatCard label="Max Drawdown"
          value={max_drawdown > 0 ? `-${(max_drawdown * 100).toFixed(2)}%` : '0.00%'}
          color={max_drawdown > 0.1 ? 'var(--red)' : max_drawdown > 0.05 ? 'var(--amber)' : 'var(--green)'} />
      </div>

      <div className="vm-body">
        {/* ── Open Positions ── */}
        <div className="vm-section">
          <div className="vm-section-header">
            <span>Open Positions</span>
            <span className="vm-section-count">{(open_positions || []).length}</span>
          </div>
          {(open_positions || []).length === 0 ? (
            <div className="empty-state">No open positions</div>
          ) : (
            <div className="vm-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Market</th>
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
                  {open_positions.map((p, i) => (
                    <tr key={i}>
                      <td style={{ maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {p.market_question}
                      </td>
                      <td>
                        <span className={`status-pill ${p.platform === 'kalshi' ? 's-filled' : 's-dry_run'}`}>
                          {p.platform}
                        </span>
                      </td>
                      <td>
                        <span className={`cat-badge cat-${p.category}`}>{p.category || '—'}</span>
                      </td>
                      <td style={{ color: p.side === 'YES' ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
                        {p.side}
                      </td>
                      <td>{(p.entry_price * 100).toFixed(1)}¢</td>
                      <td>{fmt(p.size_usd)}</td>
                      <td style={{ color: pnlColor(p.unrealized_pnl) }}>
                        {p.unrealized_pnl != null ? fmtPnl(p.unrealized_pnl) : '—'}
                      </td>
                      <td style={{ color: 'var(--txt-sub)' }}>
                        {p.opened_at ? new Date(p.opened_at).toLocaleTimeString() : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Closed Positions ── */}
        <div className="vm-section">
          <div className="vm-section-header">
            <span>Closed Positions</span>
            <span className="vm-section-count">{(closed_positions || []).length}</span>
          </div>
          {(closed_positions || []).length === 0 ? (
            <div className="empty-state">No closed positions yet</div>
          ) : (
            <div className="vm-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Market</th>
                    <th>Platform</th>
                    <th>Category</th>
                    <th>Side</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>Size</th>
                    <th>Realized P&L</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {closed_positions.map((p, i) => (
                    <tr key={i}>
                      <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {p.market_question}
                      </td>
                      <td>
                        <span className={`status-pill ${p.platform === 'kalshi' ? 's-filled' : 's-dry_run'}`}>
                          {p.platform}
                        </span>
                      </td>
                      <td>
                        <span className={`cat-badge cat-${p.category}`}>{p.category || '—'}</span>
                      </td>
                      <td style={{ color: p.side === 'YES' ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
                        {p.side}
                      </td>
                      <td>{(p.entry_price * 100).toFixed(1)}¢</td>
                      <td>{p.exit_price != null ? `${(p.exit_price * 100).toFixed(1)}¢` : '—'}</td>
                      <td>{fmt(p.size_usd)}</td>
                      <td style={{ color: pnlColor(p.realized_pnl) }}>
                        {p.realized_pnl != null ? fmtPnl(p.realized_pnl) : '—'}
                      </td>
                      <td>
                        <span className={`status-pill ${p.realized_pnl > 0 ? 's-filled' : 's-rejected'}`}>
                          {p.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── By Category ── */}
        {by_category && Object.keys(by_category).length > 0 && (
          <div className="vm-section">
            <div className="vm-section-header">
              <span>Performance by Category</span>
            </div>
            <div className="vm-cat-grid">
              {Object.entries(by_category).map(([cat, data]) => (
                <div key={cat} className="vm-cat-card">
                  <div className="vm-cat-header">
                    <span className={`cat-badge cat-${cat}`}>{cat}</span>
                    <span style={{ color: pnlColor(data.pnl), fontSize: 13, fontWeight: 600 }}>
                      {fmtPnl(data.pnl)}
                    </span>
                  </div>
                  <div className="vm-cat-stats">
                    <span className="txt-mute">Trades:</span> {data.trades}
                    <span style={{ marginLeft: 12 }} className="txt-mute">Win rate:</span>{' '}
                    {data.win_rate != null ? `${(data.win_rate * 100).toFixed(0)}%` : '—'}
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
