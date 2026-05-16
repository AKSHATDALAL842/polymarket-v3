import usePolling from '../hooks/usePolling.js'

const API = '/api'

function timeAgo(ts) {
  if (!ts) return ''
  const diff = (Date.now() - new Date(ts).getTime()) / 1000
  if (diff < 60)   return `${Math.floor(diff)}s`
  if (diff < 3600) return `${Math.floor(diff / 60)}m`
  return `${Math.floor(diff / 3600)}h`
}

export default function NewsWire() {
  const { data } = usePolling(`${API}/news/headlines?limit=80`, 10000)

  const headlines = data?.headlines || []

  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden',
      background: 'var(--bg-base)'
    }}>
      <div style={{
        padding: '14px 18px', borderBottom: '1px solid var(--border)',
        flexShrink: 0, background: 'var(--bg-surface)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between'
      }}>
        <div>
          <div style={{
            fontFamily: '"Barlow Condensed"', fontSize: '9.5px', fontWeight: 700,
            letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--txt-mute)',
            marginBottom: '2px'
          }}>
            News Wire
          </div>
          <div style={{ fontSize: '11px', color: 'var(--txt-sub)' }}>
            Raw headline feed from all 7 sources · {data?.count ?? 0} recent
          </div>
        </div>
        <div style={{ display: 'flex', gap: '16px', fontSize: '9px', color: 'var(--txt-mute)' }}>
          {['RSS','REDDIT','NEWSAPI','GNEWS','GDELT','TWITTER','TELEGRAM'].map(src => {
            const count = headlines.filter(h => h.source === src.toLowerCase()).length
            return (
              <span key={src} style={{
                fontFamily: '"Barlow Condensed"', fontWeight: count > 0 ? 600 : 400,
                color: count > 0 ? 'var(--amber)' : 'var(--txt-mute)',
                fontSize: '8.5px', letterSpacing: '0.08em'
              }}>
                {src} {count}
              </span>
            )
          })}
        </div>
      </div>

      <div style={{
        flex: 1, overflowY: 'auto', overflowX: 'hidden',
        scrollbarWidth: 'thin', scrollbarColor: 'var(--border-hi) transparent'
      }}>
        {headlines.length === 0 ? (
          <div className="empty-state" style={{ paddingTop: '40px' }}>
            <div style={{ marginBottom: '8px', fontSize: '20px' }}>◌</div>
            <div>No headlines yet</div>
            <div style={{ marginTop: '4px', fontSize: '9px' }}>Start the pipeline to ingest news</div>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: '70px' }}>Age</th>
                <th style={{ width: '80px' }}>Source</th>
                <th>Headline</th>
                <th style={{ width: '60px', textAlign: 'right' }}>Latency</th>
              </tr>
            </thead>
            <tbody>
              {headlines.map((h, i) => (
                <tr key={i}>
                  <td className="txt-mute" style={{ fontSize: '9.5px', fontFamily: '"Barlow Condensed"', fontWeight: 600 }}>
                    {timeAgo(h.received_at)}
                  </td>
                  <td>
                    <span className={`sig-source ${h.source?.toLowerCase()}`}>{h.source}</span>
                  </td>
                  <td style={{
                    maxWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    fontSize: '10.5px', color: 'var(--txt)'
                  }} title={h.headline}>
                    {h.headline}
                  </td>
                  <td className="txt-mute" style={{ fontSize: '9.5px', textAlign: 'right' }}>
                    {h.latency_ms ?? '—'}ms
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
