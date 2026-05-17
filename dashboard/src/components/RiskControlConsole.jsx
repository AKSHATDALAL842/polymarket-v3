import { useState, useCallback, useEffect, useRef } from 'react'

const API = '/api'

/* ────────────────────────────────────────────
   Config key → console state mapping
   ──────────────────────────────────────────── */
const CFG = {
  positionSize:     'MAX_BET_USD',
  maxBets:          'MAX_CONCURRENT_POSITIONS',
  dailyExposure:    'DAILY_LOSS_LIMIT_USD',
  confidenceThresh: 'MIN_CONFIDENCE',
  kellyFraction:    'SIZING_K',
  cooldownMin:      'COOLDOWN_MINUTES',
  newsWeight:       'NEWS_WEIGHT',
  momentumWeight:   'MOMENTUM_WEIGHT',
  spreadTolerance:  'MAX_SPREAD_FRACTION',
  slippageLimit:    'MAX_SLIPPAGE_FRACTION',
  liquidityFloor:   'MIN_LIQUIDITY_SCORE',
}

const PRESETS = {
  safe:       { positionSize: 15,  maxBets: 3,  dailyExposure: 50,  confidenceThresh: 0.70, kellyFraction: 0.10, cooldownMin: 60, newsWeight: 0.80, momentumWeight: 0.20, spreadTolerance: 0.03, slippageLimit: 0.01, liquidityFloor: 0.35 },
  balanced:   { positionSize: 25,  maxBets: 5,  dailyExposure: 100, confidenceThresh: 0.55, kellyFraction: 0.25, cooldownMin: 30, newsWeight: 0.60, momentumWeight: 0.40, spreadTolerance: 0.05, slippageLimit: 0.02, liquidityFloor: 0.25 },
  aggressive: { positionSize: 40,  maxBets: 8,  dailyExposure: 200, confidenceThresh: 0.45, kellyFraction: 0.40, cooldownMin: 15, newsWeight: 0.45, momentumWeight: 0.55, spreadTolerance: 0.08, slippageLimit: 0.03, liquidityFloor: 0.15 },
  sniper:     { positionSize: 50,  maxBets: 2,  dailyExposure: 80,  confidenceThresh: 0.65, kellyFraction: 0.30, cooldownMin: 5,  newsWeight: 0.70, momentumWeight: 0.30, spreadTolerance: 0.04, slippageLimit: 0.01, liquidityFloor: 0.30 },
}

/* ────────────────────────────────────────────
   Sub-components
   ──────────────────────────────────────────── */

function SectionLabel({ children }) {
  return (
    <div style={{
      fontFamily: '"Barlow Condensed"', fontSize: '8px', fontWeight: 600,
      letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--txt-mute)',
      marginBottom: '8px', paddingBottom: '4px', borderBottom: '1px solid var(--border-dim)'
    }}>
      {children}
    </div>
  )
}

function Slider({ label, value, min, max, step, onChange, leftLabel, rightLabel }) {
  const pct = ((value - min) / (max - min)) * 100
  return (
    <div style={{ marginBottom: '8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
        <span style={{ fontFamily: '"Barlow Condensed"', fontSize: '9px', fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--txt-sub)' }}>
          {label}
        </span>
        <span style={{ fontSize: '10px', fontVariantNumeric: 'tabular-nums', color: 'var(--amber)' }}>
          {typeof value === 'number' ? value.toFixed(2) : value}
        </span>
      </div>
      <div style={{ position: 'relative', height: '16px', display: 'flex', alignItems: 'center' }}>
        <input
          type="range"
          min={min} max={max} step={step} value={value}
          onChange={e => onChange(parseFloat(e.target.value))}
          style={{
            width: '100%', height: '2px', appearance: 'none',
            background: `linear-gradient(to right, var(--border) 0%, var(--border) ${pct}%, var(--amber) ${pct}%, var(--amber) ${pct + 0.5}%, var(--border) ${pct + 0.5}%, var(--border) 100%)`,
            outline: 'none', cursor: 'pointer',
          }}
        />
        <div style={{
          position: 'absolute', left: `${pct}%`, top: '50%',
          transform: 'translate(-50%, -50%)',
          width: '8px', height: '8px', borderRadius: '50%',
          background: 'var(--amber)', pointerEvents: 'none',
          boxShadow: '0 0 6px rgba(232,153,13,0.5)',
        }} />
      </div>
      {(leftLabel || rightLabel) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '1px' }}>
          <span style={{ fontSize: '7.5px', color: 'var(--txt-mute)', fontFamily: '"Barlow Condensed"' }}>{leftLabel}</span>
          <span style={{ fontSize: '7.5px', color: 'var(--txt-mute)', fontFamily: '"Barlow Condensed"' }}>{rightLabel}</span>
        </div>
      )}
    </div>
  )
}

function Toggle({ label, value, onChange, disabled }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '3px 0', opacity: disabled ? 0.4 : 1
    }}>
      <span style={{ fontFamily: '"Barlow Condensed"', fontSize: '9px', fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--txt-sub)' }}>
        {label}
      </span>
      <button
        onClick={() => !disabled && onChange(!value)}
        disabled={disabled}
        style={{
          width: '32px', height: '16px', borderRadius: '8px', border: 'none',
          background: value ? 'var(--green)' : 'var(--border)',
          position: 'relative', cursor: disabled ? 'default' : 'pointer',
          transition: 'background 0.2s'
        }}
      >
        <div style={{
          position: 'absolute', top: '2px',
          left: value ? '18px' : '2px',
          width: '12px', height: '12px', borderRadius: '50%',
          background: 'var(--bg-base)',
          transition: 'left 0.2s'
        }} />
      </button>
    </div>
  )
}

function NumericInput({ label, value, onChange, min, max, step, unit }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '3px 0'
    }}>
      <span style={{ fontFamily: '"Barlow Condensed"', fontSize: '9px', fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--txt-sub)' }}>
        {label}
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
        <button
          onClick={() => onChange(Math.max(min, value - step))}
          style={{
            background: 'transparent', border: '1px solid var(--border)',
            color: 'var(--txt-sub)', fontSize: '10px', width: '18px', height: '18px',
            cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: '"JetBrains Mono"'
          }}
        >−</button>
        <input
          type="text"
          value={value}
          onChange={e => {
            const n = parseFloat(e.target.value)
            if (!isNaN(n)) onChange(Math.max(min, Math.min(max, n)))
          }}
          style={{
            width: '48px', textAlign: 'center',
            background: 'var(--bg-base)', border: '1px solid var(--border)',
            color: 'var(--amber)', fontFamily: '"JetBrains Mono"', fontSize: '10px',
            padding: '2px 0', outline: 'none', fontVariantNumeric: 'tabular-nums'
          }}
        />
        <button
          onClick={() => onChange(Math.min(max, value + step))}
          style={{
            background: 'transparent', border: '1px solid var(--border)',
            color: 'var(--txt-sub)', fontSize: '10px', width: '18px', height: '18px',
            cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: '"JetBrains Mono"'
          }}
        >+</button>
        {unit && <span style={{ fontSize: '9px', color: 'var(--txt-sub)', marginLeft: '2px' }}>{unit}</span>}
      </div>
    </div>
  )
}

function SegmentedControl({ options, value, onChange }) {
  return (
    <div style={{
      display: 'flex', border: '1px solid var(--border)',
      background: 'var(--bg-base)'
    }}>
      {options.map(opt => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          style={{
            flex: 1, padding: '4px 0',
            fontFamily: '"Barlow Condensed"', fontSize: '9px', fontWeight: 600,
            letterSpacing: '0.1em', textTransform: 'uppercase',
            color: value === opt.value ? 'var(--bg-base)' : 'var(--txt-sub)',
            background: value === opt.value ? opt.color || 'var(--amber)' : 'transparent',
            border: 'none', cursor: 'pointer', transition: 'all 0.15s'
          }}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

function ExposureBar({ label, pct, color }) {
  return (
    <div style={{ marginBottom: '3px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1px' }}>
        <span style={{ fontSize: '8.5px', color: 'var(--txt-sub)', fontFamily: '"Barlow Condensed"', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
          {label}
        </span>
        <span style={{ fontSize: '9px', color: 'var(--txt-mute)', fontVariantNumeric: 'tabular-nums' }}>
          {pct}%
        </span>
      </div>
      <div style={{ height: '3px', background: 'var(--border)', overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${pct}%`,
          background: color || 'var(--amber)',
          transition: 'width 0.5s ease'
        }} />
      </div>
    </div>
  )
}

function RejectionLog({ rejections }) {
  if (!rejections || rejections.length === 0) {
    return (
      <div style={{ fontSize: '9px', color: 'var(--txt-mute)', fontFamily: '"Barlow Condensed"', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        No recent rejections
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
      {rejections.slice(0, 4).map((r, i) => (
        <div key={i} style={{
          fontSize: '8.5px', color: 'var(--red)', fontFamily: '"JetBrains Mono"',
          padding: '2px 6px', background: 'var(--red-dim)', borderLeft: '2px solid var(--red)'
        }}>
          {r}
        </div>
      ))}
    </div>
  )
}

/* ────────────────────────────────────────────
   Main Component
   ──────────────────────────────────────────── */

export default function RiskControlConsole({ status, stats, tradingStatus, portfolio }) {
  const risk    = status?.risk       || {}
  const wsOk    = status?.ws_connected ?? false
  const trades  = stats?.trades      || {}
  const cal     = stats?.calibration || {}

  // ── State ────────────────────────────────────
  const [riskLevel, setRiskLevel] = useState(50)
  const [positionSize, setPositionSize] = useState(25)
  const [maxBets, setMaxBets] = useState(5)
  const [dailyExposure, setDailyExposure] = useState(100)
  const [confidenceThresh, setConfidenceThresh] = useState(0.55)
  const [kellyFraction, setKellyFraction] = useState(0.25)
  const [cooldownMin, setCooldownMin] = useState(30)
  const [newsWeight, setNewsWeight] = useState(0.60)
  const [momentumWeight, setMomentumWeight] = useState(0.40)
  const [spreadTolerance, setSpreadTolerance] = useState(0.05)
  const [slippageLimit, setSlippageLimit] = useState(0.02)
  const [liquidityFloor, setLiquidityFloor] = useState(0.25)
  const [execMode, setExecMode] = useState(tradingStatus?.mode || 'DRY_RUN')
  const [autoExecute, setAutoExecute] = useState(false)
  const [killSwitch, setKillSwitch] = useState(false)
  const [activePreset, setActivePreset] = useState('balanced')
  const [synced, setSynced] = useState(false)
  const [modeLoading, setModeLoading] = useState(false)

  // Debounce timer ref
  const debounceRef = useRef(null)

  // ── Fetch current config from backend on mount ──
  useEffect(() => {
    fetch(`${API}/config/risk`)
      .then(r => r.json())
      .then(data => {
        const eff = data.effective || {}
        if (eff.MAX_BET_USD)       setPositionSize(eff.MAX_BET_USD)
        if (eff.MAX_CONCURRENT_POSITIONS) setMaxBets(eff.MAX_CONCURRENT_POSITIONS)
        if (eff.DAILY_LOSS_LIMIT_USD)     setDailyExposure(eff.DAILY_LOSS_LIMIT_USD)
        if (eff.MIN_CONFIDENCE)     setConfidenceThresh(eff.MIN_CONFIDENCE)
        if (eff.SIZING_K)           setKellyFraction(eff.SIZING_K)
        if (eff.COOLDOWN_MINUTES)   setCooldownMin(eff.COOLDOWN_MINUTES)
        if (eff.NEWS_WEIGHT != null)      setNewsWeight(eff.NEWS_WEIGHT)
        if (eff.MOMENTUM_WEIGHT != null)  setMomentumWeight(eff.MOMENTUM_WEIGHT)
        if (eff.MAX_SPREAD_FRACTION)      setSpreadTolerance(eff.MAX_SPREAD_FRACTION)
        if (eff.MAX_SLIPPAGE_FRACTION)    setSlippageLimit(eff.MAX_SLIPPAGE_FRACTION)
        if (eff.MIN_LIQUIDITY_SCORE)      setLiquidityFloor(eff.MIN_LIQUIDITY_SCORE)
        setSynced(true)
      })
      .catch(() => setSynced(true)) // backend may not be running yet
  }, [])

  // ── Push config changes to backend (debounced) ──
  const pushConfig = useCallback((overrides) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      fetch(`${API}/config/risk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ overrides }),
      }).catch(() => {})
    }, 400)
  }, [])

  // Helpers to build the override payload
  const syncState = (stateKey, value) => {
    const cfgKey = CFG[stateKey]
    if (!cfgKey) return
    pushConfig({ [cfgKey]: value })
  }

  // ── Presets ──
  const applyPreset = useCallback((key) => {
    const p = PRESETS[key]
    if (!p) return
    setActivePreset(key)
    setPositionSize(p.positionSize)
    setMaxBets(p.maxBets)
    setDailyExposure(p.dailyExposure)
    setConfidenceThresh(p.confidenceThresh)
    setKellyFraction(p.kellyFraction)
    setCooldownMin(p.cooldownMin)
    setNewsWeight(p.newsWeight)
    setMomentumWeight(p.momentumWeight)
    setSpreadTolerance(p.spreadTolerance)
    setSlippageLimit(p.slippageLimit)
    setLiquidityFloor(p.liquidityFloor)
    const levels = { safe: 20, balanced: 50, aggressive: 80, sniper: 65 }
    setRiskLevel(levels[key] || 50)

    // Push ALL values
    pushConfig({
      [CFG.positionSize]:     p.positionSize,
      [CFG.maxBets]:          p.maxBets,
      [CFG.dailyExposure]:    p.dailyExposure,
      [CFG.confidenceThresh]: p.confidenceThresh,
      [CFG.kellyFraction]:    p.kellyFraction,
      [CFG.cooldownMin]:      p.cooldownMin,
      [CFG.newsWeight]:       p.newsWeight,
      [CFG.momentumWeight]:   p.momentumWeight,
      [CFG.spreadTolerance]:  p.spreadTolerance,
      [CFG.slippageLimit]:    p.slippageLimit,
      [CFG.liquidityFloor]:   p.liquidityFloor,
    })
  }, [pushConfig])

  // ── Mode switching ──
  const switchMode = useCallback(async (mode) => {
    setExecMode(mode)
    setModeLoading(true)
    try {
      await fetch(`${API}/trading/mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, confirm: mode === 'LIVE' }),
      })
    } catch {}
    setModeLoading(false)
  }, [])

  // ── Derived data ──
  const buildRejections = () => {
    const r = []
    const byStatus = trades.by_status || {}
    if (byStatus.rejected_spread) r.push(`SPREAD · ${byStatus.rejected_spread} rejected`)
    if (byStatus.rejected_slippage) r.push(`SLIPPAGE · ${byStatus.rejected_slippage} rejected`)
    if (byStatus.rejected_daily_limit) r.push(`DAILY LIMIT · ${byStatus.rejected_daily_limit} hit`)
    if (byStatus.rejected_max_positions) r.push(`MAX POSITIONS · ${byStatus.rejected_max_positions} hit`)
    if (byStatus.rejected_cooldown) r.push(`COOLDOWN · ${byStatus.rejected_cooldown} active`)
    if (byStatus.rejected_category_exposure) r.push(`CATEGORY EXP · ${byStatus.rejected_category_exposure} breached`)
    const errorCount = Object.entries(byStatus)
      .filter(([k]) => k.startsWith('error'))
      .reduce((s, [, v]) => s + v, 0)
    if (errorCount > 0) r.push(`EXEC ERRORS · ${errorCount}`)
    return r
  }

  const rejections = buildRejections()
  const executed = (trades.by_status?.executed || 0) + (trades.by_status?.paper || 0) + (trades.by_status?.dry_run || 0)
  const capitalUsed = portfolio?.total_value || (risk.total_exposure || 0)
  const capitalMax  = portfolio?.initial_balance || 10000
  const capitalPct  = Math.min(100, Math.round((capitalUsed / capitalMax) * 100))

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
      background: 'var(--bg-surface)', borderTop: '1px solid var(--border)'
    }}>
      {/* Header */}
      <div className="section-hdr">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="section-hdr-label">Risk Control Console</span>
          {synced && (
            <span style={{
              fontSize: '7px', fontFamily: '"Barlow Condensed"', fontWeight: 600,
              letterSpacing: '0.1em', color: 'var(--green)', textTransform: 'uppercase'
            }}>
              ● LIVE
            </span>
          )}
        </div>
        <div className="section-hdr-right">
          <span className="section-hdr-dot" style={{
            background: killSwitch ? 'var(--red)' : wsOk ? 'var(--green)' : 'var(--red)',
            boxShadow: killSwitch ? '0 0 6px var(--red)' : wsOk ? '0 0 4px rgba(26,158,75,0.5)' : 'none',
            animation: killSwitch ? 'pulse-red 1s ease-in-out infinite' : wsOk ? 'pulse-green 2s ease-in-out infinite' : 'none'
          }} />
          <span style={{
            fontFamily: '"Barlow Condensed"', fontSize: '9px', fontWeight: 600,
            color: killSwitch ? 'var(--red)' : wsOk ? 'var(--green)' : 'var(--red)',
            letterSpacing: '0.1em'
          }}>
            {killSwitch ? 'KILLED' : wsOk ? 'LIVE' : 'OFFLINE'}
          </span>
        </div>
      </div>

      {/* Scrollable body */}
      <div style={{
        flex: 1, overflowY: 'auto', overflowX: 'hidden',
        padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: '10px',
        scrollbarWidth: 'thin', scrollbarColor: 'var(--border-hi) transparent'
      }}>

        {/* ── Master Risk Slider ── */}
        <div>
          <SectionLabel>Master Risk Profile</SectionLabel>
          <Slider
            label="Risk Level"
            value={riskLevel} min={0} max={100} step={1}
            onChange={v => {
              setRiskLevel(v)
              if (v <= 25) applyPreset('safe')
              else if (v >= 75) applyPreset('aggressive')
              else applyPreset('balanced')
            }}
            leftLabel="CONSERVATIVE" rightLabel="AGGRESSIVE"
          />
          <div style={{ marginTop: '6px' }}>
            <SegmentedControl
              options={[
                { value: 'safe',       label: 'SAFE',       color: 'var(--green)' },
                { value: 'balanced',   label: 'BALANCED',   color: 'var(--amber)' },
                { value: 'aggressive', label: 'AGGRESSIVE', color: '#e87d3e' },
                { value: 'sniper',     label: 'SNIPER',     color: '#c084fc' },
              ]}
              value={activePreset}
              onChange={applyPreset}
            />
          </div>
        </div>

        {/* ── Active Capital ── */}
        <div>
          <SectionLabel>Active Capital</SectionLabel>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
            <span style={{ fontSize: '13px', fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: 'var(--txt)' }}>
              ${capitalUsed.toLocaleString()}
            </span>
            <span style={{ fontSize: '10px', color: 'var(--txt-sub)', fontVariantNumeric: 'tabular-nums' }}>
              / ${capitalMax.toLocaleString()}
            </span>
          </div>
          <div style={{ height: '4px', background: 'var(--border)', overflow: 'hidden' }}>
            <div style={{
              height: '100%', width: `${capitalPct}%`,
              background: capitalPct > 60 ? 'var(--amber)' : 'var(--green)',
              transition: 'width 0.5s ease'
            }} />
          </div>
          <div style={{ textAlign: 'right', marginTop: '1px' }}>
            <span style={{ fontSize: '9px', color: 'var(--txt-mute)', fontVariantNumeric: 'tabular-nums' }}>
              {capitalPct}% deployed
            </span>
          </div>
        </div>

        {/* ── Risk Profile Controls ── */}
        <div>
          <SectionLabel>Risk Parameters</SectionLabel>
          <NumericInput label="Position Size"   value={positionSize}     onChange={v => { setPositionSize(v); syncState('positionSize', v) }}     min={1} max={100} step={1} unit="$" />
          <NumericInput label="Max Bets"        value={maxBets}          onChange={v => { setMaxBets(v); syncState('maxBets', v) }}              min={1} max={15} step={1} />
          <NumericInput label="Daily Exposure"  value={dailyExposure}    onChange={v => { setDailyExposure(v); syncState('dailyExposure', v) }}    min={10} max={500} step={10} unit="$" />
          <NumericInput label="Confidence Min"  value={confidenceThresh} onChange={v => { setConfidenceThresh(v); syncState('confidenceThresh', v) }} min={0.30} max={0.90} step={0.05} />
          <NumericInput label="Kelly Fraction"  value={kellyFraction}    onChange={v => { setKellyFraction(v); syncState('kellyFraction', v) }}    min={0.05} max={0.60} step={0.05} />
          <NumericInput label="Cooldown"        value={cooldownMin}      onChange={v => { setCooldownMin(v); syncState('cooldownMin', v) }}        min={0} max={120} step={5} unit="m" />
        </div>

        {/* ── Signal Filters ── */}
        <div>
          <SectionLabel>Signal Filters</SectionLabel>
          <Slider label="News Weight"       value={newsWeight}      min={0} max={1} step={0.05} onChange={v => { setNewsWeight(v); syncState('newsWeight', v) }}           leftLabel="0" rightLabel="1.0" />
          <Slider label="Momentum Weight"   value={momentumWeight}  min={0} max={1} step={0.05} onChange={v => { setMomentumWeight(v); syncState('momentumWeight', v) }}   leftLabel="0" rightLabel="1.0" />
          <Slider label="Spread Tolerance"  value={spreadTolerance} min={0.01} max={0.12} step={0.01} onChange={v => { setSpreadTolerance(v); syncState('spreadTolerance', v) }} />
          <Slider label="Slippage Limit"    value={slippageLimit}   min={0.01} max={0.06} step={0.01} onChange={v => { setSlippageLimit(v); syncState('slippageLimit', v) }} />
          <Slider label="Liquidity Floor"   value={liquidityFloor}  min={0.05} max={0.50} step={0.05} onChange={v => { setLiquidityFloor(v); syncState('liquidityFloor', v) }} />
        </div>

        {/* ── Exposure Heatmap ── */}
        <div>
          <SectionLabel>Category Exposure</SectionLabel>
          {(Object.entries(risk?.category_exposure || {}).length > 0
            ? Object.entries(risk.category_exposure).slice(0, 6).map(([cat, exp]) => ({
                label: cat.toUpperCase(),
                pct: Math.min(100, Math.round((exp / (dailyExposure || 100)) * 100)),
                color: exp > (dailyExposure || 100) * 0.6 ? 'var(--red)' : 'var(--amber)'
              }))
            : [
                { label: 'NO DATA', pct: 0, color: 'var(--txt-mute)' },
              ]
          ).map(e => (
            <ExposureBar key={e.label} {...e} />
          ))}
        </div>

        {/* ── Execution Controls ── */}
        <div>
          <SectionLabel>Execution</SectionLabel>
          <div style={{ marginBottom: '6px' }}>
            <SegmentedControl
              options={[
                { value: 'DRY_RUN', label: 'PAPER',  color: 'var(--amber)' },
                { value: 'LIVE',    label: 'LIVE',   color: 'var(--red)' },
              ]}
              value={execMode}
              onChange={switchMode}
            />
          </div>
          {modeLoading && (
            <div style={{ fontSize: '9px', color: 'var(--amber)', marginBottom: '4px', fontFamily: '"JetBrains Mono"' }}>
              Switching mode...
            </div>
          )}
          <div style={{ opacity: 0.5 }}>
            <Toggle label="Auto Execute (Manual Only)" value={autoExecute} onChange={setAutoExecute} disabled={true} />
          </div>
          <div style={{ fontSize: '7px', color: 'var(--txt-mute)', marginTop: '-6px', marginBottom: '4px', fontFamily: '"Barlow Condensed"', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
            Phase 1 — manual approval required
          </div>
          <div style={{ marginTop: '8px' }}>
            <button
              onClick={() => {
                if (!killSwitch) {
                  fetch(`${API}/live/hard-stop?reason=console_kill_switch`, { method: 'POST' })
                    .then(() => setKillSwitch(true))
                    .catch(() => setKillSwitch(true))
                } else {
                  fetch(`${API}/live/clear-stop`, { method: 'POST' })
                    .then(() => setKillSwitch(false))
                    .catch(() => setKillSwitch(false))
                }
              }}
              style={{
                width: '100%', padding: '6px 0',
                fontFamily: '"Barlow Condensed"', fontSize: '11px', fontWeight: 700,
                letterSpacing: '0.18em', textTransform: 'uppercase',
                color: killSwitch ? 'var(--bg-base)' : 'var(--red)',
                background: killSwitch ? 'var(--red)' : 'transparent',
                border: '1.5px solid var(--red)',
                cursor: 'pointer', transition: 'all 0.15s'
              }}
            >
              {killSwitch ? '■ KILL SWITCH ACTIVE' : '□ KILL SWITCH'}
            </button>
          </div>
          <div style={{
            marginTop: '6px', display: 'flex', justifyContent: 'space-between',
            fontSize: '9px', color: 'var(--txt-sub)'
          }}>
            <span>Executed: <span style={{ color: 'var(--green)' }}>{executed}</span></span>
            <span>Rejected: <span style={{ color: 'var(--red)' }}>{rejections.length > 0 ? rejections.length : 0}</span></span>
          </div>
        </div>

        {/* ── Signal Rejection Panel ── */}
        <div>
          <SectionLabel>Signal Rejections</SectionLabel>
          <RejectionLog rejections={rejections} />
        </div>

        {/* ── Micro Telemetry ── */}
        <div style={{
          borderTop: '1px solid var(--border-dim)', paddingTop: '6px',
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1px 8px'
        }}>
          {[
            { l: 'Brier', v: cal.brier_score != null ? cal.brier_score.toFixed(3) : '—' },
            { l: 'ECE',   v: cal.ece != null ? cal.ece.toFixed(3) : '—' },
            { l: 'Sharpe', v: portfolio?.sharpe_ratio != null ? portfolio.sharpe_ratio.toFixed(2) : '—' },
            { l: 'DD',    v: portfolio?.max_drawdown != null ? `${(portfolio.max_drawdown * 100).toFixed(1)}%` : '—' },
            { l: 'WR',    v: portfolio?.win_rate != null ? `${(portfolio.win_rate * 100).toFixed(0)}%` : '—' },
            { l: 'OPEN',  v: risk.open_positions ?? 0 },
          ].map(r => (
            <div key={r.l} style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ fontSize: '8px', color: 'var(--txt-mute)', fontFamily: '"Barlow Condensed"', letterSpacing: '0.08em', textTransform: 'uppercase' }}>{r.l}</span>
              <span style={{ fontSize: '9.5px', color: 'var(--txt-sub)', fontVariantNumeric: 'tabular-nums' }}>{r.v}</span>
            </div>
          ))}
        </div>

      </div>
    </div>
  )
}
