import { useState, useEffect } from 'react'
import StatusBar          from './components/StatusBar.jsx'
import SignalFeed         from './components/SignalFeed.jsx'
import HeroCommandCenter  from './components/HeroCommandCenter.jsx'
import ExecutionPipeline  from './components/ExecutionPipeline.jsx'
import EquityCurve        from './components/EquityCurve.jsx'
import OperatorConsole    from './components/OperatorConsole.jsx'
import MarketTable        from './components/MarketTable.jsx'
import RiskControlConsole from './components/RiskControlConsole.jsx'
import PredictionTool     from './components/PredictionTool.jsx'
import VirtualMoney       from './components/VirtualMoney.jsx'
import NewsWire           from './components/NewsWire.jsx'
import useWebSocket       from './hooks/useWebSocket.js'
import usePolling         from './hooks/usePolling.js'

const WS_URL  = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/signals`
const API     = '/api'

const TABS = [
  { id: 'terminal',  label: 'Terminal' },
  { id: 'news',      label: 'News Wire' },
  { id: 'portfolio', label: 'Portfolio' },
]

export default function App() {
  const [activeTab, setActiveTab] = useState('terminal')

  const { connected, lastMessage } = useWebSocket(WS_URL)
  const [signals, setSignals] = useState([])

  const { data: statusData  } = usePolling(`${API}/status`,          5000)
  const { data: statsData   } = usePolling(`${API}/stats`,           5000)
  const { data: marketsData } = usePolling(`${API}/markets`,        30000)
  const { data: sourcesData } = usePolling(`${API}/sources`,        10000)
  const { data: tradesData  } = usePolling(`${API}/signals/recent?limit=25`, 10000)
  const { data: portfolioData } = usePolling(`${API}/portfolio`,    5000)
  const { data: tradingStatusData } = usePolling(`${API}/trading/status`, 5000)

  // Seed signal feed from REST on first load so it's not empty
  useEffect(() => {
    if (tradesData?.signals && signals.length === 0) {
      setSignals(tradesData.signals.slice(0, 15))
    }
  }, [tradesData, signals.length])

  // Push new WS signals to top of feed
  useEffect(() => {
    if (!lastMessage || lastMessage.type !== 'signal') return
    setSignals(prev => [{ ...lastMessage, _isNew: true }, ...prev].slice(0, 150))
  }, [lastMessage])

  const status   = statusData
  const stats    = statsData
  const markets  = marketsData?.markets  || []
  const sources  = sourcesData
  const portfolio = portfolioData
  const tradingStatus = tradingStatusData

  return (
    <div className="app-wrap">
      <StatusBar
        status={status}
        connected={connected}
        tradingStatus={tradingStatus}
        sources={sources}
      />

      {/* ── Tab bar ── */}
      <div style={{
        display: 'flex', borderBottom: '1px solid var(--border)',
        flexShrink: 0, background: 'var(--bg-surface)'
      }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            style={{
              fontFamily: '"Barlow Condensed"', fontSize: '10px', fontWeight: 600,
              letterSpacing: '0.14em', textTransform: 'uppercase',
              color: activeTab === t.id ? 'var(--amber)' : 'var(--txt-sub)',
              padding: '7px 16px', cursor: 'pointer', background: 'transparent',
              border: 'none', borderBottom: '2px solid',
              borderBottomColor: activeTab === t.id ? 'var(--amber)' : 'transparent',
              marginBottom: '-1px', transition: 'all 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === 'terminal' && (
        <>
          <div className="app-body">
            <div className="app-col-left">
              <SignalFeed signals={signals} />
            </div>
            <div className="app-col-center">
              <HeroCommandCenter portfolio={portfolio} stats={stats} status={status} markets={markets} />
              <ExecutionPipeline status={status} signals={signals} sources={sources} stats={stats} />
              <EquityCurve portfolio={portfolio} />
              <div className="tables-row">
                <MarketTable markets={markets} />
                <RiskControlConsole status={status} stats={stats} tradingStatus={tradingStatus} portfolio={portfolio} />
              </div>
            </div>
            <div className="app-col-right">
              <OperatorConsole sources={sources} status={status} stats={stats} portfolio={portfolio} tradingStatus={tradingStatus} />
            </div>
          </div>
          <PredictionTool />
        </>
      )}

      {activeTab === 'news' && (
        <NewsWire />
      )}

      {activeTab === 'portfolio' && (
        <VirtualMoney />
      )}
    </div>
  )
}
