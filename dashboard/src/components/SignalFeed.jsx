import { useRef, useEffect } from 'react'

function timeAgo(ts) {
  if (!ts) return ''
  const diff = (Date.now() - new Date(ts).getTime()) / 1000
  if (diff < 60)   return `${Math.floor(diff)}s`
  if (diff < 3600) return `${Math.floor(diff / 60)}m`
  return `${Math.floor(diff / 3600)}h`
}

function fmtEV(ev) {
  if (ev == null) return '—'
  return (ev > 0 ? '+' : '') + (ev * 100).toFixed(1) + '%'
}

function SignalEntry({ signal, isNew }) {
  const src = (signal.source || signal.news_source || 'rss').toLowerCase()
  const side = signal.side?.toUpperCase()
  const ev = signal.ev ?? signal.edge
  const bet = signal.bet_usd ?? signal.bet_amount ?? signal.amount_usd
  const lat = signal.latency_ms ?? signal.total_latency_ms
  const market = signal.market || signal.market_question || '—'
  const headline = signal.headline || signal.headlines || ''

  return (
    <div className={`signal-entry${isNew ? ' is-new' : ''}`}>
      <div className="sig-top">
        <span className={`sig-source ${src}`}>{src}</span>
        {side && (
          <span className={`sig-dir ${side === 'YES' ? 'yes' : 'no'}`}>
            {side === 'YES' ? '▲ YES' : '▼ NO'}
          </span>
        )}
        <span className="sig-age">{timeAgo(signal.timestamp || signal.created_at)}</span>
      </div>

      <div className="sig-market" title={market}>
        {market}
      </div>

      {headline && (
        <div className="sig-headline" title={headline}>
          {headline}
        </div>
      )}

      <div className="sig-stats">
        {ev != null && (
          <div className="sig-stat">
            <span className="sig-stat-lbl">EV</span>
            <span className={`sig-stat-val ${ev > 0 ? 'txt-green' : 'txt-red'}`}>
              {fmtEV(ev)}
            </span>
          </div>
        )}
        {bet != null && (
          <div className="sig-stat">
            <span className="sig-stat-lbl">BET</span>
            <span className="sig-stat-val txt-amber">${Number(bet).toFixed(2)}</span>
          </div>
        )}
        {lat != null && (
          <div className="sig-stat">
            <span className="sig-stat-lbl">LAT</span>
            <span className="sig-stat-val txt-sub">{lat}ms</span>
          </div>
        )}
        {signal.status && (
          <div className="sig-stat" style={{ marginLeft: 'auto' }}>
            <span className={`status-pill s-${signal.status}`}>{signal.status}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default function SignalFeed({ signals }) {
  const listRef = useRef(null)
  const prevLen = useRef(0)

  useEffect(() => {
    if (signals.length > prevLen.current && listRef.current) {
      listRef.current.scrollTop = 0
    }
    prevLen.current = signals.length
  }, [signals.length])

  return (
    <div className="signal-feed-panel">
      <div className="section-hdr">
        <span className="section-hdr-label">Signal Feed</span>
        <div className="section-hdr-right">
          <span className="section-hdr-dot" style={{ background: 'var(--amber)', boxShadow: '0 0 5px var(--amber)', animation: 'pulse-amber 2s ease-in-out infinite' }} />
          <span className="num">{signals.length}</span>
        </div>
      </div>

      <div className="signal-list" ref={listRef}>
        {signals.length === 0 ? (
          <div className="empty-state" style={{ paddingTop: '40px' }}>
            <div style={{ marginBottom: '8px', fontSize: '20px' }}>◌</div>
            <div>Awaiting Signals</div>
            <div style={{ marginTop: '4px', fontSize: '9px' }}>Engine online — listening</div>
          </div>
        ) : (
          signals.map((s, i) => (
            <SignalEntry key={s.id || s.market_id || i} signal={s} isNew={i === 0 && s._isNew} />
          ))
        )}
      </div>
    </div>
  )
}
