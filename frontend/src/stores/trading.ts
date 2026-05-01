import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getBalance, getPositions, getStrategies, getStrategiesStats, getTradeHistory, getSymbols } from '../api'

export interface Strategy {
  id: string
  name: string
  strategy_type: string
  is_active: boolean
  symbols: string[]
  decision_mode: 'technical' | 'ai' | 'hybrid'
  leverage: number
  order_amount_usdt: number
  mgn_mode: string
  poll_interval: number
  params: Record<string, any>
  ai_min_confidence: number
  ai_prompt: string
}

export interface Position {
  symbol: string
  direction: 'long' | 'short'
  quantity: number
  entry_price: number
  current_price: number
  unrealized_pnl: number
  leverage: number
  margin_mode: string
  tp_price: number | null
  sl_price: number | null
  tp_distance_pct: number | null
  sl_distance_pct: number | null
  holding_seconds: number
  strategy_id: string | null
}

export interface AccountInfo {
  total_equity: number
  available_balance: number
  unrealized_pnl: number
  mode: string
}

export interface StrategyStats {
  total_pnl: number
  total_trades: number
  win_rate: number
  active_positions: number
}

export interface LogEntry {
  time: string
  type: 'signal' | 'trade' | 'error' | 'info'
  message: string
}

export const useTradingStore = defineStore('trading', () => {
  const account = ref<AccountInfo>({
    total_equity: 0,
    available_balance: 0,
    unrealized_pnl: 0,
    mode: '模拟盘',
  })

  const strategies = ref<Strategy[]>([])
  const strategyStats = ref<Record<string, StrategyStats>>({})
  const positions = ref<Position[]>([])
  const trades = ref<any[]>([])
  const symbols = ref<any[]>([])
  const logs = ref<LogEntry[]>([])
  const strategyLogs = ref<Record<string, LogEntry[]>>({})
  const loading = ref(false)
  const wsConnected = ref(false)

  let ws: WebSocket | null = null
  let reconnectTimer: number | null = null
  let shouldReconnect = false

  async function fetchAccount() {
    try {
      const { data } = await getBalance()
      account.value = data
    } catch (e) {
      console.error('获取账户信息失败', e)
    }
  }

  async function fetchStrategies() {
    try {
      const { data } = await getStrategies()
      strategies.value = data
    } catch (e) {
      console.error('获取策略失败', e)
    }
  }

  async function fetchStrategiesStats() {
    try {
      const { data } = await getStrategiesStats()
      strategyStats.value = data
    } catch (e) {
      console.error('获取策略统计失败', e)
    }
  }

  async function fetchPositions() {
    try {
      const { data } = await getPositions()
      positions.value = data
    } catch (e) {
      console.error('获取持仓失败', e)
    }
  }

  async function fetchTrades() {
    try {
      const { data } = await getTradeHistory()
      trades.value = data
    } catch (e) {
      console.error('获取交易历史失败', e)
    }
  }

  async function fetchSymbols() {
    try {
      const { data } = await getSymbols()
      symbols.value = data
    } catch (e) {
      console.error('获取交易对失败', e)
    }
  }

  async function fetchAll() {
    loading.value = true
    await Promise.allSettled([
      fetchAccount(),
      fetchStrategies(),
      fetchStrategiesStats(),
      fetchPositions(),
      fetchTrades(),
      fetchSymbols(),
    ])
    loading.value = false
  }

  function addLog(type: LogEntry['type'], message: string) {
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    logs.value.unshift({ time, type, message })
    if (logs.value.length > 200) {
      logs.value = logs.value.slice(0, 200)
    }
  }

  function addStrategyLog(strategyId: string, type: LogEntry['type'], message: string) {
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    if (!strategyLogs.value[strategyId]) {
      strategyLogs.value[strategyId] = []
    }
    strategyLogs.value[strategyId].unshift({ time, type, message })
    if (strategyLogs.value[strategyId].length > 200) {
      strategyLogs.value[strategyId] = strategyLogs.value[strategyId].slice(0, 200)
    }
  }

  function connectWS() {
    shouldReconnect = true
    if (ws) return

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    ws = new WebSocket(`${protocol}//${location.host}/ws`)

    ws.onopen = () => {
      wsConnected.value = true
      addLog('info', 'WebSocket 已连接')
      // 心跳
      setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send('ping')
        }
      }, 30000)
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        const sid = msg.data?.strategy_id || ''
        if (msg.event === 'signal') {
          const logMsg = `📡 ${msg.data.symbol} | ${msg.data.signal?.reason || ''}`
          addLog('signal', logMsg)
          if (sid) addStrategyLog(sid, 'signal', logMsg)
        } else if (msg.event === 'trade') {
          const logMsg = `✅ ${msg.data.symbol} ${msg.data.direction} @ ${msg.data.price}`
          addLog('trade', logMsg)
          if (sid) addStrategyLog(sid, 'trade', logMsg)
          fetchPositions()
          fetchAccount()
          fetchTrades()
        } else if (msg.event === 'strategy_status') {
          const s = strategies.value.find((s) => s.id === msg.data.id)
          if (s) s.is_active = msg.data.is_active
        } else if (msg.event === 'error') {
          const logMsg = `❌ ${msg.data.message}`
          addLog('error', logMsg)
          if (sid) addStrategyLog(sid, 'error', logMsg)
        }
      } catch {
        // ignore non-JSON (pong)
      }
    }

    ws.onclose = () => {
      wsConnected.value = false
      ws = null
      if (shouldReconnect) {
        addLog('info', 'WebSocket 已断开，5秒后重连...')
        reconnectTimer = window.setTimeout(() => connectWS(), 5000)
      }
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function disconnectWS() {
    shouldReconnect = false
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    ws?.close()
    ws = null
  }

  return {
    account,
    strategies,
    strategyStats,
    positions,
    trades,
    symbols,
    logs,
    strategyLogs,
    loading,
    wsConnected,
    fetchAccount,
    fetchStrategies,
    fetchStrategiesStats,
    fetchPositions,
    fetchTrades,
    fetchSymbols,
    fetchAll,
    addLog,
    addStrategyLog,
    connectWS,
    disconnectWS,
  }
})
