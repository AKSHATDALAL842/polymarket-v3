import { useRef, useEffect } from 'react'

function timeAgo(ts) {
  if (!ts) return ''
  const diff = (Date.now() - new Date(ts).getTime()) / 1000
  if (diff < 60)   return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

function fmtEV(ev) {
  if (ev == null) return '—'
  return (ev > 0 ? '+' : '') + (ev * 100).toFixed(1) + '%'
}

function SignalEntry({ signal, isNew }) {
  const src = (signal.source || signal.news_source || 'rss').toLowerCase()
  const side = signal.side?.toUpperCase()
  const ev = signal.ev
  const bet = signal.bet_usd ?? signal.bet_amount
  const lat = signal.latency_ms ?? signal.total_latency_ms

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

      <div className="sig-market" title={signal.market || signal.market_question}>
        {signal.market || signal.market_question || '—'}
      </div>

      <div className="sig-headline" title={signal.headline || signal.headlines}>
        {signal.headline || signal.headlines || ''}
      </div>

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

  // Auto-scroll to top when new signals arrive
  useEffect(() => {
    if (signals.length > prevLen.current && listRef.current) {
      listRef.current.scrollTop = 0
    }
    prevLen.current = signals.length
  }, [signals.length])

  return (
    <div className="panel" style={{ gridRow: '1 / span 1' }}>
      <div className="ph">
        <span className="ph-label">Live Signal Feed</span>
        <div className="ph-right">
          <span className="ws-dot" style={{ background: 'var(--amber)', animation: 'pulse-green 2s ease-in-out infinite' }} />
          <span className="num">{signals.length}</span>
        </div>
      </div>

      <div className="signal-list" ref={listRef}>
        {signals.length === 0 ? (
          <div className="empty-state" style={{ paddingTop: '40px' }}>
            <div style={{ marginBottom: '8px', fontSize: '20px' }}>◌</div>
            <div>Waiting for signals</div>
            <div style={{ marginTop: '4px', fontSize: '9.5px' }}>Connect backend to stream live events</div>
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
