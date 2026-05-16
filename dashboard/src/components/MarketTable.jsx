function fmtVol(v) {
  if (v == null) return '—'
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`
  return `$${v}`
}

function fmtDate(d) {
  if (!d) return '—'
  try {
    return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  } catch { return '—' }
}

function daysLeft(d) {
  if (!d) return null
  try {
    const diff = (new Date(d) - Date.now()) / 86400000
    return Math.ceil(diff)
  } catch { return null }
}

function LiquityDot({ score }) {
  const c = score > 0.5 ? 'var(--green)' : score > 0.2 ? 'var(--amber)' : 'var(--red)'
  return <span className="liq-dot" style={{ background: c, boxShadow: `0 0 4px ${c}` }} />
}

export default function MarketTable({ markets }) {
  return (
    <div className="table-panel">
      <div className="section-hdr">
        <span className="section-hdr-label">Tracked Markets</span>
        <span className="section-hdr-right">
          <span className="section-hdr-dot" style={{ background: 'var(--amber)', boxShadow: '0 0 4px var(--amber)' }} />
          <span className="num">{markets.length}</span>
        </span>
      </div>
      <div className="data-table-wrap">
        {markets.length === 0 ? (
          <div className="empty-state">No markets loaded</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: '38%' }}>Question</th>
                <th>Cat</th>
                <th>YES</th>
                <th>Prob</th>
                <th>Vol</th>
                <th>Ends</th>
              </tr>
            </thead>
            <tbody>
              {markets.map((m) => {
                const days = daysLeft(m.end_date)
                const urgency = days != null && days <= 3 ? 'var(--red)'
                  : days != null && days <= 7 ? 'var(--amber)'
                  : days != null && days <= 30 ? 'var(--txt-sub)'
                  : 'var(--txt-mute)'
                const cat = m.category?.toLowerCase()

                return (
                  <tr key={m.condition_id}>
                    <td style={{
                      maxWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      fontSize: '10.5px',
                    }} title={m.question}>
                      {m.question}
                    </td>
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
                        <span className={`cat-badge cat-${cat}`}>{cat}</span>
                        <span className="platform-badge platform-poly">
                          {m.source === 'kalshi' ? 'KALSHI' : 'POLY'}
                        </span>
                      </div>
                    </td>
                    <td style={{
                      fontFamily: '"Barlow Condensed"', fontWeight: 600, fontSize: '10.5px',
                      color: m.yes_price > 0.5 ? 'var(--green)' : 'var(--red)'
                    }}>
                      {(m.yes_price * 100).toFixed(0)}¢
                    </td>
                    <td>
                      <div className="price-bar-wrap">
                        <div className="price-bar-bg">
                          <div className="price-bar-fill" style={{ width: `${m.yes_price * 100}%` }} />
                        </div>
                        <span className="num" style={{ fontSize: '9.5px' }}>
                          {(m.yes_price * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    <td className="txt-sub" style={{ fontSize: '10px' }}>{fmtVol(m.volume)}</td>
                    <td>
                      <span style={{ color: urgency, fontSize: '9.5px', fontFamily: '"Barlow Condensed"', fontWeight: 600 }}>
                        {days != null ? (days <= 0 ? 'TODAY' : `${days}D`) : fmtDate(m.end_date)}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
