const SOURCE_ICONS = {
  rss:      '◈',
  newsapi:  '◈',
  reddit:   '◈',
  gnews:    '◈',
  gdelt:    '◈',
  twitter:  '◈',
  telegram: '◈',
}

const SOURCE_ORDER = ['rss', 'reddit', 'newsapi', 'gnews', 'gdelt', 'twitter', 'telegram']

export default function SourceMonitor({ sources }) {
  const srcs   = sources?.sources    || {}
  const counts = sources?.event_counts || {}

  const rows = SOURCE_ORDER.map(key => ({
    key,
    enabled: srcs[key]?.enabled ?? false,
    interval: srcs[key]?.interval_s,
    count: counts[key] ?? 0,
    note: srcs[key]?.note,
  }))

  const totalEvents = Object.values(counts).reduce((a, b) => a + b, 0)

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="ph">
        <span className="ph-label">News Sources</span>
        <span className="ph-right num">{totalEvents.toLocaleString()} total</span>
      </div>

      <div className="source-grid">
        {rows.map(r => (
          <div key={r.key} className="source-row">
            <span className={`source-indicator ${r.enabled ? 'on' : 'off'}`} />
            <span className={`source-name ${r.enabled ? 'on' : 'off'}`}>{r.key}</span>
            <span className="source-count num">{r.count.toLocaleString()}</span>
            {r.interval && (
              <span className="source-interval">
                {r.interval >= 60 ? `${r.interval / 60}m` : `${r.interval}s`}
              </span>
            )}
          </div>
        ))}

        {!sources && (
          <div className="empty-state">
            <span className="spinner" /> Connecting...
          </div>
        )}
      </div>
    </div>
  )
}
