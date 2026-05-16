import { useState, useRef } from 'react'

const API_BASE = '/api'

export default function PredictionTool() {
  const [query, setQuery]     = useState('')
  const [result, setResult]   = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const inputRef = useRef(null)

  async function analyze() {
    if (!query.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch(`${API_BASE}/prediction?event=${encodeURIComponent(query.trim())}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function onKey(e) {
    if (e.key === 'Enter') analyze()
    if (e.key === 'Escape') { setResult(null); setError(null) }
  }

  const cls = result?.classification
  const nlp = result?.nlp
  const matches = result?.top_market_matches || []

  return (
    <div className="prediction-bar">
      <div className="prediction-input-row">
        <span className="prediction-label">
          <span style={{ fontSize: '13px', color: 'var(--amber)' }}>⟩</span>
          PREDICT
        </span>
        <input
          ref={inputRef}
          className="prediction-input"
          type="text"
          placeholder="Enter a news headline to analyze against all tracked markets..."
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={onKey}
        />
        <button className="btn-analyze" onClick={analyze} disabled={loading || !query.trim()}>
          {loading ? <><span className="spinner" /> Analyzing</> : 'ANALYZE ↵'}
        </button>
        {(result || error) && (
          <button
            onClick={() => { setResult(null); setError(null) }}
            style={{
              background: 'transparent', border: '1px solid var(--border)',
              color: 'var(--txt-sub)', fontFamily: '"JetBrains Mono"', fontSize: '10px',
              padding: '4px 8px', cursor: 'pointer'
            }}>
            ✕
          </button>
        )}
      </div>

      {error && (
        <div style={{ marginTop: '8px', color: 'var(--red)', fontSize: '10px' }}>
          ERROR: {error} — is the backend running?
        </div>
      )}

      {result && (
        <div className="prediction-results">
          {/* NLP */}
          <div>
            <div className="pred-section-label">NLP Analysis</div>
            <div className="pred-row">
              <span className="pred-key">Category</span>
              <span className="pred-val" style={{ color: 'var(--amber)' }}>{nlp?.category || '—'}</span>
            </div>
            <div className="pred-row">
              <span className="pred-key">Sentiment</span>
              <span className="pred-val" style={{
                color: nlp?.sentiment > 0 ? 'var(--green)' : nlp?.sentiment < 0 ? 'var(--red)' : 'var(--txt-sub)'
              }}>
                {nlp?.sentiment != null ? (nlp.sentiment > 0 ? '+' : '') + nlp.sentiment.toFixed(3) : '—'}
              </span>
            </div>
            <div className="pred-row">
              <span className="pred-key">Impact</span>
              <span className="pred-val" style={{
                color: nlp?.impact_score > 0.5 ? 'var(--amber)' : 'var(--txt-sub)'
              }}>
                {nlp?.impact_score?.toFixed(3) ?? '—'}
              </span>
            </div>
            <div style={{ marginTop: '4px', display: 'flex', flexWrap: 'wrap', gap: '1px' }}>
              {nlp?.entities?.slice(0, 5).map((e, i) => (
                <span key={i} className="entity-tag">
                  {e.text} <span className="txt-mute">{e.label}</span>
                </span>
              ))}
            </div>
          </div>

          {/* Classification */}
          <div>
            <div className="pred-section-label">Classification</div>
            <div className="pred-row">
              <span className="pred-key">Direction</span>
              <span className="pred-val" style={{
                fontFamily: '"Barlow Condensed"', fontWeight: 700, fontSize: '12px', letterSpacing: '0.06em',
                color: cls?.direction === 'YES' ? 'var(--green)' : cls?.direction === 'NO' ? 'var(--red)' : 'var(--txt-sub)'
              }}>
                {cls?.direction === 'YES' ? '▲ YES' : cls?.direction === 'NO' ? '▼ NO' : cls?.direction || '—'}
              </span>
            </div>
            <div className="pred-row">
              <span className="pred-key">Confidence</span>
              <span className="pred-val">
                {cls?.confidence != null ? (cls.confidence * 100).toFixed(0) + '%' : '—'}
              </span>
            </div>
            <div className="pred-row">
              <span className="pred-key">Materiality</span>
              <span className="pred-val">
                {cls?.materiality != null ? (cls.materiality * 100).toFixed(0) + '%' : '—'}
              </span>
            </div>
            <div className="pred-row">
              <span className="pred-key">Actionable</span>
              <span className="pred-val" style={{
                fontFamily: '"Barlow Condensed"', fontWeight: 700,
                color: cls?.actionable ? 'var(--green)' : 'var(--red)'
              }}>
                {cls?.actionable ? 'TRUE' : 'FALSE'}
              </span>
            </div>
          </div>

          {/* Reasoning */}
          <div>
            <div className="pred-section-label">Reasoning</div>
            <div style={{
              fontSize: '10px', color: 'var(--txt-sub)', lineHeight: '1.6',
              maxHeight: '80px', overflow: 'hidden', textOverflow: 'ellipsis'
            }}>
              {cls?.reasoning || <span className="txt-mute">No reasoning returned</span>}
            </div>
          </div>

          {/* Market matches */}
          <div>
            <div className="pred-section-label">Top Matches</div>
            {matches.length === 0 ? (
              <div className="txt-mute" style={{ fontSize: '10px' }}>No matches</div>
            ) : (
              matches.map((m, i) => (
                <div key={i} className="market-match-row">
                  <span className="match-sim">{(m.similarity * 100).toFixed(0)}%</span>
                  <span className="match-q" title={m.market}>{m.market}</span>
                  <span className="txt-sub num" style={{ marginLeft: 'auto', flexShrink: 0, fontSize: '9.5px' }}>
                    {(m.yes_price * 100).toFixed(0)}¢
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
