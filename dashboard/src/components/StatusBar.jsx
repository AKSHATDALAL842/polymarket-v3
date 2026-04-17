import { useState, useEffect } from 'react'
import TradingModeControl from './TradingModeControl.jsx'

function fmtUptime(s) {
  if (!s && s !== 0) return '—'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s % 60}s`
  return `${s}s`
}

function Stat({ label, value, color }) {
  return (
    <div className="sb-stat">
      <span className="sb-stat-label">{label}</span>
      <span className="sb-stat-value" style={color ? { color } : {}}>
        {value ?? '—'}
      </span>
    </div>
  )
}

export default function StatusBar({ status, connected, tradingStatus, onModeChange }) {
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const utc = time.toISOString().slice(11, 19)
  const risk = status?.risk || {}

  return (
    <div className="statusbar">
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <span className="sb-brand">POLYMARKET SIGNAL SYSTEM</span>
        <span className="sb-version">V3</span>
      </div>

      <div className="sb-center">
        <Stat label="Uptime"   value={fmtUptime(status?.uptime_seconds)} />
        <Stat label="Events"   value={status?.events_processed?.toLocaleString()} />
        <Stat label="Signals"  value={status?.signals_generated} color="var(--amber)" />
        <Stat label="Markets"  value={status?.tracked_markets} />
        <Stat label="Cooldown" value={risk.in_cooldown ? 'YES' : 'NO'}
          color={risk.in_cooldown ? 'var(--red)' : 'var(--green)'} />
        <Stat label="Daily P&L"
          value={risk.daily_pnl != null ? `$${risk.daily_pnl?.toFixed(2)}` : '—'}
          color={risk.daily_pnl > 0 ? 'var(--green)' : risk.daily_pnl < 0 ? 'var(--red)' : undefined} />
      </div>

      <div className="sb-right">
        <TradingModeControl tradingStatus={tradingStatus} onModeChange={onModeChange} />
        <div className={`ws-badge ${connected ? 'live' : 'offline'}`}>
          <span className="ws-dot" />
          {connected ? 'LIVE' : 'OFFLINE'}
        </div>
        <span className="utc-clock">{utc} <span className="txt-mute">UTC</span></span>
      </div>
    </div>
  )
}
