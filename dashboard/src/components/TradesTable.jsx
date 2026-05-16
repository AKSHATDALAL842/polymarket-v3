function fmtTime(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    })
  } catch { return '—' }
}

function fmtMS(ms) {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export default function TradesTable({ trades }) {
  return (
    <div className="table-panel">
      <div className="section-hdr">
        <span className="section-hdr-label">Recent Trades</span>
        <span className="section-hdr-right">
          <span className="section-hdr-dot" style={{
            background: trades.length > 0 ? 'var(--green)' : 'var(--txt-mute)',
            boxShadow: trades.length > 0 ? '0 0 4px rgba(26,158,75,0.5)' : 'none'
          }} />
          <span className="num">{trades.length}</span>
        </span>
      </div>
      <div className="data-table-wrap">
        {trades.length === 0 ? (
          <div className="empty-state">No trades recorded yet</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Time</th>
                <th style={{ width: '34%' }}>Market</th>
                <th>Dir</th>
                <th>Size</th>
                <th>EV</th>
                <th>Lat</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => {
                const ev = t.ev
                const lat = t.total_latency_ms ?? t.latency_ms
                return (
                  <tr key={t.id || i}>
                    <td className="txt-sub" style={{ fontSize: '9.5px' }}>{fmtTime(t.created_at)}</td>
                    <td style={{
                      maxWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      fontSize: '10px',
                    }} title={t.market_question}>
                      {t.market_question || '—'}
                    </td>
                    <td>
                      <span style={{
                        fontFamily: '"Barlow Condensed"', fontWeight: 700, fontSize: '10px',
                        letterSpacing: '0.06em',
                        color: t.side === 'YES' ? 'var(--green)' : 'var(--red)'
                      }}>
                        {t.side === 'YES' ? '▲ YES' : t.side === 'NO' ? '▼ NO' : t.side || '—'}
                      </span>
                    </td>
                    <td style={{ color: 'var(--amber)', fontSize: '10px' }}>
                      ${Number(t.bet_amount || t.bet_usd || 0).toFixed(2)}
                    </td>
                    <td>
                      <span style={{
                        fontSize: '9.5px',
                        color: ev > 0 ? 'var(--green)' : ev < 0 ? 'var(--red)' : 'var(--txt-sub)'
                      }}>
                        {ev != null ? ((ev > 0 ? '+' : '') + (ev * 100).toFixed(1) + '%') : '—'}
                      </span>
                    </td>
                    <td className="txt-mute" style={{ fontSize: '9.5px' }}>
                      {fmtMS(lat)}
                    </td>
                    <td>
                      <span className={`status-pill s-${t.status}`}>{t.status || '—'}</span>
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
