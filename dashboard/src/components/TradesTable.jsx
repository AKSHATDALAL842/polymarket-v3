function fmtTime(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    })
  } catch { return '—' }
}

export default function TradesTable({ trades }) {
  return (
    <div className="panel" style={{ flex: '0 0 auto', maxHeight: '220px' }}>
      <div className="ph">
        <span className="ph-label">Recent Trades</span>
        <span className="ph-right num">{trades.length}</span>
      </div>
      <div className="data-table-wrap">
        {trades.length === 0 ? (
          <div className="empty-state">No trades recorded yet</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Time</th>
                <th style={{ width: '35%' }}>Market</th>
                <th>Dir</th>
                <th>Size</th>
                <th>EV</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => {
                const ev = t.ev
                return (
                  <tr key={t.id || i}>
                    <td className="txt-sub" style={{ fontSize: '10px' }}>{fmtTime(t.created_at)}</td>
                    <td style={{ maxWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={t.market_question}>
                      {t.market_question || '—'}
                    </td>
                    <td>
                      <span className={t.side === 'YES' ? 'txt-green' : 'txt-red'}
                            style={{ fontFamily: '"Barlow Condensed"', fontWeight: 700, fontSize: '11px' }}>
                        {t.side === 'YES' ? '▲ YES' : t.side === 'NO' ? '▼ NO' : t.side || '—'}
                      </span>
                    </td>
                    <td className="txt-amber">${Number(t.bet_amount || 0).toFixed(2)}</td>
                    <td>
                      <span className={ev > 0 ? 'txt-green' : ev < 0 ? 'txt-red' : 'txt-sub'}>
                        {ev != null ? ((ev > 0 ? '+' : '') + (ev * 100).toFixed(1) + '%') : '—'}
                      </span>
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
