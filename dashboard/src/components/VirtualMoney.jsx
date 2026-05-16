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
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-base)' }}>
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
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg-base)' }}>

      {/* ── Hero Banner ── */}
      <div style={{
        display: 'flex', alignItems: 'stretch', borderBottom: '1px solid var(--border)',
        flexShrink: 0, background: 'var(--bg-surface)'
      }}>
        <div style={{ flex: 1, padding: '20px 28px', borderRight: '1px solid var(--border)' }}>
          <div style={{
            fontFamily: '"Barlow Condensed"', fontSize: '9px', fontWeight: 700,
            letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--txt-mute)', marginBottom: '4px'
          }}>
            Virtual Portfolio · Paper Trading
          </div>
          <div style={{
            fontSize: '38px', fontWeight: 700, fontVariantNumeric: 'tabular-nums',
            color: 'var(--txt)', lineHeight: 1, letterSpacing: '-0.5px'
          }}>
            {fmt(p.total_value)}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--txt-sub)', marginTop: '6px' }}>
            Started with {fmt(p.initial_balance)} ·{' '}
            <span style={{ fontSize: '13px', fontWeight: 600, color: pnlColor(p.total_return_pct) }}>
              {returnSign}{(p.total_return_pct || 0).toFixed(2)}% total return
            </span>
          </div>
        </div>

        {/* Stat strip */}
        <div style={{ display: 'flex' }}>
          {[
            { label: 'Win Rate', value: p.win_rate > 0 ? `${(p.win_rate * 100).toFixed(1)}%` : '—', color: p.win_rate >= 0.5 ? 'var(--green)' : p.win_rate > 0 ? 'var(--red)' : 'var(--txt-sub)' },
            { label: 'Sharpe', value: p.sharpe_ratio != null ? p.sharpe_ratio.toFixed(2) : '—', color: p.sharpe_ratio > 1 ? 'var(--green)' : p.sharpe_ratio > 0 ? 'var(--amber)' : 'var(--txt-sub)' },
            { label: 'Max Drawdown', value: p.max_drawdown > 0 ? `-${(p.max_drawdown * 100).toFixed(2)}%` : '0.00%', color: p.max_drawdown > 0.1 ? 'var(--red)' : p.max_drawdown > 0.05 ? 'var(--amber)' : 'var(--green)' },
            { label: 'Open Positions', value: openList.length, color: openList.length > 0 ? 'var(--amber)' : 'var(--txt-sub)' },
            { label: 'Cash Balance', value: fmt(p.balance), color: 'var(--txt)' },
          ].map(({ label, value, color }) => (
            <div key={label} style={{
              padding: '16px 20px', display: 'flex', flexDirection: 'column',
              justifyContent: 'center', gap: '4px', borderRight: '1px solid var(--border)',
              minWidth: '110px'
            }}>
              <span style={{
                fontFamily: '"Barlow Condensed"', fontSize: '8.5px', fontWeight: 700,
                letterSpacing: '0.16em', textTransform: 'uppercase', color: 'var(--txt-mute)'
              }}>
                {label}
              </span>
              <span style={{
                fontSize: '17px', fontWeight: 600, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1, color
              }}>
                {value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ── P&L strip ── */}
      <div style={{
        display: 'flex', alignItems: 'stretch', borderBottom: '1px solid var(--border)',
        flexShrink: 0, background: 'var(--bg-base)'
      }}>
        {[
          { label: 'Unrealized P&L', value: p.unrealized_pnl },
          { label: 'Realized P&L',   value: p.realized_pnl },
          { label: 'Total P&L',      value: totalPnl },
          { label: 'Daily P&L',      value: p.daily_pnl ?? null },
        ].map(({ label, value }) => (
          <div key={label} style={{
            flex: 1, padding: '12px 18px', borderRight: '1px solid var(--border)',
            display: 'flex', flexDirection: 'column', gap: '3px', position: 'relative'
          }}>
            <div style={{
              position: 'absolute', top: 0, left: 0, right: 0, height: '2px',
              background: value > 0 ? 'var(--green)' : value < 0 ? 'var(--red)' : 'var(--border-hi)'
            }} />
            <span style={{
              fontFamily: '"Barlow Condensed"', fontSize: '8.5px', fontWeight: 700,
              letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--txt-mute)'
            }}>
              {label}
            </span>
            <span style={{
              fontSize: '19px', fontWeight: 600, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1, color: pnlColor(value)
            }}>
              {fmtPnl(value)}
            </span>
          </div>
        ))}
      </div>

      {/* ── Body: Tables ── */}
      <div style={{
        flex: 1, overflowY: 'auto', padding: '14px 18px',
        display: 'flex', flexDirection: 'column', gap: '14px'
      }}>

        {/* Open Positions */}
        <div style={{
          background: 'var(--bg-surface)', border: '1px solid var(--border)', overflow: 'hidden'
        }}>
          <div className="section-hdr">
            <span className="section-hdr-label">Open Positions</span>
            <span style={{
              fontFamily: '"Barlow Condensed"', fontSize: '9.5px', fontWeight: 700,
              background: 'var(--bg-base)', border: '1px solid var(--border-hi)',
              color: 'var(--txt)', padding: '1px 8px'
            }}>
              {openList.length}
            </span>
          </div>
          {openList.length === 0 ? (
            <div className="empty-state" style={{ borderTop: '1px dashed var(--border-dim)' }}>
              No open positions — waiting for signals
            </div>
          ) : (
            <div className="data-table-wrap" style={{ maxHeight: '300px' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ minWidth: 240 }}>Market</th>
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
                      <td style={{ maxWidth: 320, whiteSpace: 'normal', wordBreak: 'break-word', color: 'var(--txt)', fontSize: '10.5px', lineHeight: 1.4 }}>
                        {pos.question || pos.market_question || pos.market_id}
                      </td>
                      <td>
                        <span className={`status-pill s-${pos.platform === 'kalshi' ? 'filled' : 'dry_run'}`}>
                          {pos.platform}
                        </span>
                      </td>
                      <td>
                        {pos.category
                          ? <span className={`cat-badge cat-${pos.category}`}>{pos.category}</span>
                          : <span className="txt-mute">—</span>}
                      </td>
                      <td>
                        <span style={{
                          color: pos.side === 'YES' ? 'var(--green)' : 'var(--red)',
                          fontWeight: 700, fontFamily: '"Barlow Condensed"',
                          fontSize: '11px', letterSpacing: '0.06em'
                        }}>
                          {pos.side}
                        </span>
                      </td>
                      <td className="txt-sub" style={{ fontSize: '10px' }}>{(pos.entry_price * 100).toFixed(1)}¢</td>
                      <td style={{ color: 'var(--txt)', fontSize: '10px' }}>{fmt(pos.size_usd)}</td>
                      <td style={{ color: pnlColor(pos.unrealized_pnl), fontWeight: 600, fontSize: '10px' }}>
                        {pos.unrealized_pnl != null ? fmtPnl(pos.unrealized_pnl) : '—'}
                      </td>
                      <td className="txt-mute" style={{ fontSize: '9.5px' }}>
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
        <div style={{
          background: 'var(--bg-surface)', border: '1px solid var(--border)', overflow: 'hidden'
        }}>
          <div className="section-hdr">
            <span className="section-hdr-label">Closed Positions</span>
            <span style={{
              fontFamily: '"Barlow Condensed"', fontSize: '9.5px', fontWeight: 700,
              background: 'var(--bg-base)', border: '1px solid var(--border-hi)',
              color: 'var(--txt)', padding: '1px 8px'
            }}>
              {closedList.length}
            </span>
          </div>
          {closedList.length === 0 ? (
            <div className="empty-state" style={{ borderTop: '1px dashed var(--border-dim)' }}>
              No closed positions yet
            </div>
          ) : (
            <div className="data-table-wrap" style={{ maxHeight: '300px' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ minWidth: 220 }}>Market</th>
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
                      <td style={{ maxWidth: 280, whiteSpace: 'normal', wordBreak: 'break-word', color: 'var(--txt)', fontSize: '10.5px', lineHeight: 1.4 }}>
                        {pos.question || pos.market_question || pos.market_id}
                      </td>
                      <td>
                        <span className={`status-pill s-${pos.platform === 'kalshi' ? 'filled' : 'dry_run'}`}>
                          {pos.platform}
                        </span>
                      </td>
                      <td>
                        {pos.category
                          ? <span className={`cat-badge cat-${pos.category}`}>{pos.category}</span>
                          : <span className="txt-mute">—</span>}
                      </td>
                      <td>
                        <span style={{
                          color: pos.side === 'YES' ? 'var(--green)' : 'var(--red)',
                          fontWeight: 700, fontFamily: '"Barlow Condensed"',
                          fontSize: '11px', letterSpacing: '0.06em'
                        }}>
                          {pos.side}
                        </span>
                      </td>
                      <td className="txt-sub" style={{ fontSize: '10px' }}>{(pos.entry_price * 100).toFixed(1)}¢</td>
                      <td className="txt-sub" style={{ fontSize: '10px' }}>
                        {pos.exit_price != null ? `${(pos.exit_price * 100).toFixed(1)}¢` : '—'}
                      </td>
                      <td style={{ color: 'var(--txt)', fontSize: '10px' }}>{fmt(pos.size_usd)}</td>
                      <td style={{ color: pnlColor(pos.realized_pnl), fontWeight: 600, fontSize: '10px' }}>
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

        {/* Category breakdown */}
        {cats.length > 0 && (
          <div style={{
            background: 'var(--bg-surface)', border: '1px solid var(--border)', overflow: 'hidden'
          }}>
            <div className="section-hdr">
              <span className="section-hdr-label">Performance by Category</span>
              <span style={{
                fontFamily: '"Barlow Condensed"', fontSize: '9.5px', fontWeight: 700,
                background: 'var(--bg-base)', border: '1px solid var(--border-hi)',
                color: 'var(--txt)', padding: '1px 8px'
              }}>
                {cats.length}
              </span>
            </div>
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 0
            }}>
              {cats.map(([cat, data]) => (
                <div key={cat} style={{
                  padding: '12px 16px', borderRight: '1px solid var(--border-dim)',
                  borderBottom: '1px solid var(--border-dim)',
                  display: 'flex', flexDirection: 'column', gap: '6px'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span className={`cat-badge cat-${cat}`}>{cat}</span>
                    <span style={{ fontSize: '14px', fontWeight: 600, color: pnlColor(data.pnl) }}>
                      {fmtPnl(data.pnl)}
                    </span>
                  </div>
                  {data.win_rate != null && (
                    <div style={{ height: '2px', background: 'var(--border)', borderRadius: '1px', overflow: 'hidden' }}>
                      <div style={{
                        height: '100%', borderRadius: '1px',
                        width: `${(data.win_rate || 0) * 100}%`,
                        background: data.win_rate >= 0.5 ? 'var(--green)' : 'var(--red)'
                      }} />
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: '12px', fontSize: '10px', color: 'var(--txt-sub)' }}>
                    <span><span className="txt-mute" style={{ fontFamily: '"Barlow Condensed"', fontSize: '8.5px' }}>TRADES </span>{data.trades ?? '—'}</span>
                    <span>
                      <span className="txt-mute" style={{ fontFamily: '"Barlow Condensed"', fontSize: '8.5px' }}>WIN% </span>
                      <span style={{ color: data.win_rate >= 0.5 ? 'var(--green)' : 'var(--red)' }}>
                        {data.win_rate != null ? `${(data.win_rate * 100).toFixed(0)}%` : '—'}
                      </span>
                    </span>
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
