import { motion } from 'framer-motion'

const STAGES = [
  { id: 'news',     label: 'NEWS',     icon: '⊡' },
  { id: 'nlp',      label: 'NLP',      icon: '⊟' },
  { id: 'signal',   label: 'SIGNAL',   icon: '⊞' },
  { id: 'validate', label: 'VALIDATE', icon: '⊗' },
  { id: 'size',     label: 'SIZE',     icon: '⊠' },
  { id: 'exec',     label: 'EXEC',     icon: '⊠' },
  { id: 'settle',   label: 'SETTLE',   icon: '⊡' },
]

function PipelineNode({ stage, isActive, isRejected, value, sub }) {
  let statusClass = ''
  if (isRejected) statusClass = 'rejected'
  else if (isActive) statusClass = 'active'

  return (
    <div className={`pipeline-node ${statusClass}`}>
      <motion.div
        className="pipeline-node-icon"
        animate={isActive ? { scale: [1, 1.08, 1] } : { scale: 1 }}
        transition={{ duration: 1.5, repeat: isActive ? Infinity : 0, ease: 'easeInOut' }}
      >
        {stage.icon}
      </motion.div>
      <span className="pipeline-node-label">{stage.label}</span>
      <span className="pipeline-node-telemetry">
        {value != null && value > 0 ? (
          <span>{Number(value).toLocaleString()}</span>
        ) : value != null && value !== 0 ? (
          <span>{value}</span>
        ) : (
          <span style={{ color: 'var(--txt-mute)' }}>—</span>
        )}
        {sub && <span style={{ marginLeft: '3px', color: 'var(--txt-mute)', fontSize: '7.5px' }}>{sub}</span>}
      </span>
      <div className="pipeline-connector" />
    </div>
  )
}

export default function ExecutionPipeline({ status, sources, stats }) {
  const eventsProcessed = status?.events_processed ?? 0
  const signalsGen      = status?.signals_generated ?? 0
  const wsConnected     = status?.ws_connected ?? false

  const trades = stats?.trades || {}
  const cal    = stats?.calibration || {}
  const byStatus = trades.by_status || {}

  // NEWS: total ingested from all sources
  const totalIngested = sources
    ? Object.values(sources.event_counts || {}).reduce((a, b) => a + b, 0)
    : 0

  // NLP: events - stale ones filtered (approx = events processed)
  const nlpPassed = eventsProcessed

  // SIGNAL: how many passed classification
  const signalsPassed = signalsGen

  // VALIDATE: trades that weren't rejected by risk
  const rejected = Object.entries(byStatus)
    .filter(([k]) => k.startsWith('rejected') || k.startsWith('error'))
    .reduce((sum, [, v]) => sum + v, 0)
  const validated = (trades.total ?? 0) - rejected

  // SIZE: all validated trades get sized
  const sized = validated

  // EXEC: executed + paper + dry_run
  const executed = (byStatus.executed || 0) + (byStatus.paper || 0) + (byStatus.dry_run || 0)

  // SETTLE: resolved markets
  const settled = cal.total ?? 0

  const hasActivity = eventsProcessed > 0

  return (
    <div className="pipeline-wrap">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
        <span style={{
          fontFamily: '"Barlow Condensed"', fontSize: '9px', fontWeight: 600,
          letterSpacing: '0.16em', textTransform: 'uppercase', color: 'var(--txt-sub)'
        }}>
          Execution Pipeline
        </span>
        <div style={{ display: 'flex', gap: '14px', fontSize: '9px', color: 'var(--txt-mute)' }}>
          <span>{eventsProcessed.toLocaleString()} events</span>
          <span>{signalsGen} signals</span>
          <span style={{
            fontFamily: '"Barlow Condensed"', fontWeight: 600,
            color: wsConnected ? 'var(--green)' : 'var(--red)'
          }}>
            {wsConnected ? 'WS LIVE' : 'WS OFF'}
          </span>
        </div>
      </div>

      <div className="pipeline-flow">
        <PipelineNode
          stage={STAGES[0]}
          isActive={totalIngested > 0}
          value={totalIngested}
        />
        <PipelineNode
          stage={STAGES[1]}
          isActive={nlpPassed > 0}
          value={nlpPassed}
          sub={nlpPassed > 0 ? 'FILTERED' : undefined}
        />
        <PipelineNode
          stage={STAGES[2]}
          isActive={signalsPassed > 0}
          value={signalsPassed}
          sub={signalsPassed > 0 ? 'CLASSIFIED' : undefined}
        />
        <PipelineNode
          stage={STAGES[3]}
          isActive={validated > 0}
          isRejected={rejected > 0}
          value={validated}
          sub={rejected > 0 ? `${rejected} REJ` : validated > 0 ? 'PASSED' : undefined}
        />
        <PipelineNode
          stage={STAGES[4]}
          isActive={sized > 0}
          value={sized}
          sub={sized > 0 ? 'KELLY' : undefined}
        />
        <PipelineNode
          stage={STAGES[5]}
          isActive={executed > 0}
          value={executed}
          sub={executed > 0 ? 'FILLED' : undefined}
        />
        <PipelineNode
          stage={STAGES[6]}
          isActive={settled > 0}
          value={settled}
          sub={settled > 0 ? 'RESOLVED' : undefined}
        />
      </div>
    </div>
  )
}
