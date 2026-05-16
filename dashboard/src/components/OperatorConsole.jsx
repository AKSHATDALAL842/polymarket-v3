const SOURCE_ORDER = ['rss', 'reddit', 'newsapi', 'gnews', 'gdelt', 'twitter', 'telegram']

function formatUSD(n) {
  if (n == null) return '—'
  return '$' + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function ConsoleSection({ label, children }) {
  return (
    <div>
      <div className="console-section-label">{label}</div>
      {children}
    </div>
  )
}

function ConsoleRow({ label, value, color }) {
  return (
    <div className="console-row">
      <span className="console-row-label">{label}</span>
      <span className="console-row-value" style={color ? { color } : {}}>
        {value ?? '—'}
      </span>
    </div>
  )
}

export default function OperatorConsole({ sources, status, stats, portfolio, tradingStatus }) {
  const srcs     = sources?.sources    || {}
  const counts   = sources?.event_counts || {}
  const risk     = status?.risk        || {}
  const trades   = stats?.trades       || {}
  const cal      = stats?.calibration  || {}
  const lat      = stats?.latency      || {}

  const totalEvents    = Object.values(counts).reduce((a, b) => a + b, 0)
  const liveSources    = SOURCE_ORDER.filter(k => srcs[k]?.enabled !== false).length
  const connected      = status?.ws_connected ?? false
  const activeAlphas   = ['news', 'momentum']
  const streak         = trades.consecutive_wins ?? 0
  const topWin         = trades.best_win ?? null
  const largestLoss    = trades.worst_loss ?? null
  const tradesPerHour  = trades.total > 0 && status?.uptime_seconds > 0
    ? (trades.total / (status.uptime_seconds / 3600)).toFixed(1)
    : null

  return (
    <div className="console-panel">
      <div className="section-hdr">
        <span className="section-hdr-label">Operator Console</span>
        <div className="section-hdr-right">
          <span className="section-hdr-dot" style={{
            background: connected ? 'var(--green)' : 'var(--red)',
            boxShadow: connected ? '0 0 5px rgba(26,158,75,0.5)' : 'none',
          }} />
          <span style={{ fontFamily: '"Barlow Condensed"', fontSize: '9px', fontWeight: 600, color: connected ? 'var(--green)' : 'var(--red)' }}>
            {connected ? 'ONLINE' : 'OFFLINE'}
          </span>
        </div>
      </div>

      <div className="console-body">

        {/* Engine */}
        <ConsoleSection label="Engine">
          <ConsoleRow label="Mode" value={tradingStatus?.mode ?? 'DRY_RUN'}
            color={tradingStatus?.is_live ? 'var(--red)' : 'var(--amber)'} />
          <ConsoleRow label="Uptime" value={
            status?.uptime_seconds
              ? `${Math.floor(status.uptime_seconds / 3600)}h ${Math.floor((status.uptime_seconds % 3600) / 60)}m`
              : '—'
          } />
          <ConsoleRow label="WS Status" value={connected ? 'CONNECTED' : 'DISCONNECTED'}
            color={connected ? 'var(--green)' : 'var(--red)'} />
          <ConsoleRow label="Cooldown" value={risk.in_cooldown ? 'ACTIVE' : 'CLEAR'}
            color={risk.in_cooldown ? 'var(--red)' : 'var(--green)'} />
        </ConsoleSection>

        <hr className="console-divider" />

        {/* Alpha Strategies */}
        <ConsoleSection label="Active Alphas">
          {activeAlphas.map(a => (
            <ConsoleRow key={a} label={a.toUpperCase()} value="RUNNING" color="var(--green)" />
          ))}
          <ConsoleRow label="Cache Hit" value={sources ? '—' : '—'} />
        </ConsoleSection>

        <hr className="console-divider" />

        {/* News Sources */}
        <ConsoleSection label={`Sources · ${liveSources}/7 live`}>
          {SOURCE_ORDER.map(key => {
            const enabled = srcs[key]?.enabled !== false
            return (
              <div key={key} className="console-source-row">
                <span className={`console-source-dot ${enabled ? 'on' : 'off'}`} />
                <span className={`console-source-name ${enabled ? 'on' : 'off'}`}>{key}</span>
                <span className="console-source-count">{counts[key]?.toLocaleString() ?? 0}</span>
              </div>
            )
          })}
          <ConsoleRow label="TOTAL" value={totalEvents.toLocaleString()} color="var(--amber)" />
        </ConsoleSection>

        <hr className="console-divider" />

        {/* Latency */}
        <ConsoleSection label="Latency">
          <ConsoleRow label="p50 Classify" value={lat.p50 != null ? `${lat.p50}ms` : '—'}
            color={lat.p50 < 2000 ? 'var(--green)' : lat.p50 < 4000 ? 'var(--amber)' : 'var(--red)'} />
          <ConsoleRow label="p95 Classify" value={lat.p95 != null ? `${lat.p95}ms` : '—'} />
          <ConsoleRow label="Avg Total" value={lat.avg_total_ms != null ? `${lat.avg_total_ms}ms` : '—'} />
          <ConsoleRow label="Avg News" value={lat.avg_news_ms != null ? `${lat.avg_news_ms}ms` : '—'} />
        </ConsoleSection>

        <hr className="console-divider" />

        {/* Session Performance */}
        <ConsoleSection label="Session">
          <ConsoleRow label="Trades/Hr" value={tradesPerHour ?? '—'} color="var(--amber)" />
          <ConsoleRow label="Win Streak" value={streak > 0 ? streak : '—'}
            color={streak > 2 ? 'var(--green)' : undefined} />
          <ConsoleRow label="Top Win" value={topWin != null ? formatUSD(topWin) : '—'} color="var(--green)" />
          <ConsoleRow label="Largest Loss" value={largestLoss != null ? formatUSD(Math.abs(largestLoss)) : '—'} color="var(--red)" />
          <ConsoleRow label="Avg Hold" value="—" />
          <ConsoleRow label="Regime" value="TRENDING" color="var(--amber)" />
        </ConsoleSection>

        <hr className="console-divider" />

        {/* Calibration */}
        <ConsoleSection label="Calibration">
          <ConsoleRow label="Brier Score" value={cal.brier_score != null ? cal.brier_score.toFixed(3) : '—'} />
          <ConsoleRow label="ECE" value={cal.ece != null ? cal.ece.toFixed(3) : '—'}
            color={cal.ece < 0.05 ? 'var(--green)' : cal.ece < 0.15 ? 'var(--amber)' : 'var(--red)'} />
          <ConsoleRow label="Resolved" value={cal.total ?? 0} />
        </ConsoleSection>

      </div>
    </div>
  )
}
