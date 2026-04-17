// dashboard/src/components/TradingModeControl.jsx
import { useState } from 'react'

const API = '/api'

export default function TradingModeControl({ tradingStatus, onModeChange }) {
  const [confirming, setConfirming] = useState(false)
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState(null)

  const isLive  = tradingStatus?.is_live ?? false
  const mode    = tradingStatus?.mode ?? 'DRY_RUN'

  async function handleToggle() {
    if (isLive) {
      // Switch back to paper — no confirmation needed
      setLoading(true)
      setError(null)
      try {
        const resp = await fetch(`${API}/trading/mode`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: 'DRY_RUN' }),
        })
        const data = await resp.json()
        if (!resp.ok) throw new Error(data.detail || 'Failed')
        onModeChange && onModeChange(data)
      } catch (e) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    } else {
      // First click → show confirmation dialog
      setConfirming(true)
    }
  }

  async function handleConfirmLive() {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch(`${API}/trading/mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'LIVE', confirm: true }),
      })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || 'Failed')
      onModeChange && onModeChange(data)
      setConfirming(false)
    } catch (e) {
      setError(e.message)
      setConfirming(false)
    } finally {
      setLoading(false)
    }
  }

  if (confirming) {
    return (
      <div className="tm-confirm-wrap">
        <span className="tm-confirm-label">ENABLE LIVE TRADING?</span>
        <button
          className="tm-btn tm-btn-confirm-yes"
          onClick={handleConfirmLive}
          disabled={loading}
        >
          {loading ? '...' : 'YES, GO LIVE'}
        </button>
        <button
          className="tm-btn tm-btn-confirm-no"
          onClick={() => { setConfirming(false); setError(null) }}
        >
          CANCEL
        </button>
        {error && <span className="tm-error">{error}</span>}
      </div>
    )
  }

  return (
    <div className="tm-wrap">
      {isLive && (
        <span className="tm-live-banner">⚠ LIVE</span>
      )}
      <button
        className={`tm-btn ${isLive ? 'tm-btn-live' : 'tm-btn-paper'}`}
        onClick={handleToggle}
        disabled={loading}
        title={isLive ? 'Switch to Paper Trading' : 'Enable Live Trading'}
      >
        {loading ? '...' : isLive ? 'LIVE' : 'PAPER'}
      </button>
      {error && <span className="tm-error">{error}</span>}
    </div>
  )
}
