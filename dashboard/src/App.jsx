import { useState, useEffect, useCallback } from 'react'
import StatusBar     from './components/StatusBar.jsx'
import SignalFeed    from './components/SignalFeed.jsx'
import MetricsGrid   from './components/MetricsGrid.jsx'
import MarketTable   from './components/MarketTable.jsx'
import TradesTable   from './components/TradesTable.jsx'
import PortfolioPanel from './components/PortfolioPanel.jsx'
import SourceMonitor  from './components/SourceMonitor.jsx'
import PredictionTool from './components/PredictionTool.jsx'
import VirtualMoney   from './components/VirtualMoney.jsx'
import useWebSocket  from './hooks/useWebSocket.js'
import usePolling    from './hooks/usePolling.js'

const WS_URL  = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/signals`
const API     = '/api'

const TABS = [
  { id: 'dashboard',     label: 'Dashboard' },
  { id: 'virtual-money', label: 'Virtual Money' },
]

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard')

  // WebSocket live signals
  const { connected, lastMessage } = useWebSocket(WS_URL)

  // Signals buffer (live WS + seeded from /signals/recent)
  const [signals, setSignals] = useState([])

  // REST data
  const { data: statusData  } = usePolling(`${API}/status`,          5000)
  const { data: statsData   } = usePolling(`${API}/stats`,           5000)
  const { data: marketsData } = usePolling(`${API}/markets`,        30000)
  const { data: sourcesData } = usePolling(`${API}/sources`,        10000)
  const { data: tradesData  } = usePolling(`${API}/signals/recent?limit=25`, 10000)
  const { data: tradingStatusData } = usePolling(`${API}/trading/status`, 5000)

  // Portfolio settings (user-editable, local only)
  const [portfolio, setPortfolio] = useState({ capital: 1000, maxBet: 25, riskFactor: 0.25 })

  // Seed signals from REST on mount
  useEffect(() => {
    if (tradesData?.signals) {
      setSignals(prev => {
        if (prev.length === 0) return tradesData.signals
        return prev
      })
    }
  }, [tradesData])

  // Push new WS signals into the feed
  useEffect(() => {
    if (!lastMessage || lastMessage.type !== 'signal') return
    setSignals(prev => [{ ...lastMessage, _isNew: true }, ...prev].slice(0, 150))
  }, [lastMessage])

  const status  = statusData
  const stats   = statsData
  const markets = marketsData?.markets  || []
  const sources = sourcesData
  const trades  = tradesData?.signals   || []

  return (
    <div className="app-wrap">
      <StatusBar status={status} connected={connected} tradingStatus={tradingStatusData} onModeChange={() => {}} />

      {/* ── Tab bar ── */}
      <div className="tabs">
        {TABS.map(t => (
          <button
            key={t.id}
            className={`tab-btn${activeTab === t.id ? ' active' : ''}`}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Tab content ── */}
      {activeTab === 'dashboard' && (
        <>
          <div className="main-grid">
            {/* LEFT: Live signal feed */}
            <SignalFeed signals={signals} />

            {/* CENTER: Metrics → Markets → Trades */}
            <div className="col-center">
              <MetricsGrid stats={stats} status={status} />
              <MarketTable markets={markets} />
              <TradesTable trades={trades} />
            </div>

            {/* RIGHT: Portfolio → Sources */}
            <div className="col-right">
              <PortfolioPanel
                stats={stats}
                status={status}
                portfolio={portfolio}
                onPortfolioChange={setPortfolio}
              />
              <SourceMonitor sources={sources} />
            </div>
          </div>

          {/* BOTTOM: Prediction tool */}
          <PredictionTool />
        </>
      )}

      {activeTab === 'virtual-money' && (
        <VirtualMoney />
      )}
    </div>
  )
}
