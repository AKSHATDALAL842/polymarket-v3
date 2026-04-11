export default function PortfolioPanel({ stats, status, portfolio, onPortfolioChange }) {
  const trades  = stats?.trades || {}
  const risk    = status?.risk   || {}

  const pnl = trades.total_pnl ?? 0
  const pnlColor = pnl > 0 ? 'var(--green)' : pnl < 0 ? 'var(--red)' : 'var(--txt)'

  const exposure = risk.total_exposure ?? 0
  const positions = risk.open_positions ?? 0
  const dailyLoss = risk.daily_pnl ?? 0

  function set(key, val) {
    const n = parseFloat(val)
    if (!isNaN(n)) onPortfolioChange(p => ({ ...p, [key]: n }))
  }

  return (
    <div className="panel" style={{ flex: '0 0 auto' }}>
      <div className="ph">
        <span className="ph-label">Portfolio</span>
        {risk.in_cooldown && (
          <span style={{
            fontFamily: '"Barlow Condensed"', fontSize: '9px', fontWeight: 700,
            letterSpacing: '0.12em', color: 'var(--red)', textTransform: 'uppercase'
          }}>
            ⬛ COOLDOWN
          </span>
        )}
      </div>

      <div className="portfolio-grid">
        {/* Live stats */}
        <div className="portfolio-stats">
          <div className="p-stat">
            <span className="p-stat-lbl">Daily P&L</span>
            <span className="p-stat-val" style={{ color: pnlColor }}>
              {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
            </span>
          </div>
          <div className="p-stat">
            <span className="p-stat-lbl">Exposure</span>
            <span className="p-stat-val txt-amber">${exposure.toFixed(2)}</span>
          </div>
          <div className="p-stat">
            <span className="p-stat-lbl">Positions</span>
            <span className="p-stat-val">{positions} <span className="txt-mute">/ {risk.max_positions ?? '—'}</span></span>
          </div>
          <div className="p-stat">
            <span className="p-stat-lbl">Total Trades</span>
            <span className="p-stat-val">{trades.total ?? 0}</span>
          </div>
        </div>

        {/* Editable settings */}
        <div className="portfolio-inputs">
          <div style={{
            fontFamily: '"Barlow Condensed"', fontSize: '9px', fontWeight: 600,
            letterSpacing: '0.14em', color: 'var(--txt-mute)', textTransform: 'uppercase',
            marginBottom: '2px'
          }}>
            Risk Settings
          </div>

          {[
            { label: 'Capital ($)', key: 'capital', prefix: '$' },
            { label: 'Max Bet ($)',  key: 'maxBet',   prefix: '$' },
            { label: 'Risk Factor', key: 'riskFactor', prefix: '' },
          ].map(({ label, key, prefix }) => (
            <div key={key} className="input-row">
              <span className="input-lbl">{label}</span>
              <input
                type="number"
                className="input-field"
                value={portfolio[key]}
                onChange={e => set(key, e.target.value)}
                step={key === 'riskFactor' ? 0.05 : 1}
                min={0}
              />
            </div>
          ))}

          <div style={{ marginTop: '4px', padding: '8px', background: 'var(--bg-elevated)', borderLeft: '2px solid var(--amber-dim)' }}>
            <div style={{ fontSize: '9.5px', color: 'var(--txt-sub)', lineHeight: '1.6' }}>
              <div><span className="txt-mute">Bankroll:</span> ${portfolio.capital?.toFixed(0)}</div>
              <div><span className="txt-mute">Max bet:</span> ${portfolio.maxBet?.toFixed(0)}</div>
              <div><span className="txt-mute">Sizing K:</span> {portfolio.riskFactor}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
