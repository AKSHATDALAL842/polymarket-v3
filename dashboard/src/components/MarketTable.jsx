function fmtVol(v) {
  if (v == null) return '—'
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`
  return `$${v}`
}

function fmtDate(d) {
  if (!d) return '—'
  try {
    const dt = new Date(d)
    return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  } catch { return '—' }
}

function daysLeft(d) {
  if (!d) return null
  try {
    const diff = (new Date(d) - Date.now()) / 86400000
    return Math.ceil(diff)
  } catch { return null }
}

export default function MarketTable({ markets }) {
  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="ph">
        <span className="ph-label">Tracked Markets</span>
        <span className="ph-right num">{markets.length}</span>
      </div>
      <div className="data-table-wrap">
        {markets.length === 0 ? (
          <div className="empty-state">No markets loaded</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: '36%' }}>Question</th>
                <th>Cat</th>
                <th>YES / NO</th>
                <th>Price</th>
                <th>Volume</th>
                <th>Ends</th>
              </tr>
            </thead>
            <tbody>
              {markets.map((m) => {
                const days = daysLeft(m.end_date)
                const urgentColor = days != null && days <= 7 ? 'var(--amber)' : days != null && days <= 30 ? 'var(--txt-sub)' : 'var(--txt-mute)'
                const cat = m.category?.toLowerCase()

                return (
                  <tr key={m.condition_id}>
                    <td style={{ maxWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={m.question}>
                      {m.question}
                    </td>
                    <td>
                      <span className={`cat-badge cat-${cat}`}>{cat}</span>
                    </td>
                    <td>
                      <span className="txt-green">{(m.yes_price * 100).toFixed(0)}¢</span>
                      <span className="txt-mute"> / </span>
                      <span className="txt-red">{(m.no_price * 100).toFixed(0)}¢</span>
                    </td>
                    <td>
                      <div className="price-bar-wrap">
                        <div className="price-bar-bg">
                          <div className="price-bar-fill" style={{ width: `${m.yes_price * 100}%` }} />
                        </div>
                        <span className="num" style={{ width: '30px', textAlign: 'right', fontSize: '10px' }}>
                          {(m.yes_price * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    <td className="txt-sub">{fmtVol(m.volume)}</td>
                    <td>
                      <span style={{ color: urgentColor, fontSize: '10px' }}>
                        {days != null ? (days <= 0 ? 'today' : `${days}d`) : fmtDate(m.end_date)}
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
