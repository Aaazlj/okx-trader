import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

const PERPETUAL_ANALYSIS_TIMEOUT_MS = 60 * 60 * 1000

type UnauthorizedHandler = (() => void) | null

let unauthorizedHandler: UnauthorizedHandler = null

export function setUnauthorizedHandler(handler: UnauthorizedHandler) {
  unauthorizedHandler = handler
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      unauthorizedHandler?.()
    }
    return Promise.reject(error)
  },
)

export interface AuthStatus {
  enabled: boolean
  authenticated: boolean
}

// ═══════════════════════════════════════════
// 面板登录
// ═══════════════════════════════════════════

export const getAuthStatus = () => api.get<AuthStatus>('/auth/status')
export const login = (password: string) => api.post('/auth/login', { password })

// ═══════════════════════════════════════════
// 账户
// ═══════════════════════════════════════════

export const getBalance = () => api.get('/account/balance')
export const getPositions = () => api.get('/positions')

// ═══════════════════════════════════════════
// 策略
// ═══════════════════════════════════════════

export const getStrategies = () => api.get('/strategies')
export const getStrategy = (id: string) => api.get(`/strategies/${id}`)
export const updateStrategy = (id: string, data: any) => api.patch(`/strategies/${id}`, data)
export const startStrategy = (id: string) => api.post(`/strategies/${id}/start`)
export const stopStrategy = (id: string) => api.post(`/strategies/${id}/stop`)

// 策略详情相关
export const getStrategiesStats = () => api.get('/strategies/stats')
export const getStrategyPositions = (id: string) => api.get(`/strategies/${id}/positions`)
export const getStrategySignals = (id: string, limit = 200) =>
  api.get(`/strategies/${id}/signals`, { params: { limit } })
export const getStrategyPnl = (id: string) => api.get(`/strategies/${id}/pnl`)
export const generateMartingaleParams = (data: any) => api.post('/martingale/params/generate', data)
export const runMartingaleBacktest = (data: any) => api.post('/backtests/martingale', data, { timeout: PERPETUAL_ANALYSIS_TIMEOUT_MS })
export const downloadBacktestCandles = (data: any) =>
  api.post('/backtests/candles/download', data, { timeout: PERPETUAL_ANALYSIS_TIMEOUT_MS })
export const getBacktestCandleCoverage = (params: any) =>
  api.get('/backtests/candles/coverage', { params })
export const getMartingaleBacktestRecords = (params: any = {}) =>
  api.get('/backtests/martingale/records', { params })
export const getMartingaleBacktestRecord = (id: number | string) =>
  api.get(`/backtests/martingale/records/${id}`)

// ═══════════════════════════════════════════
// 市场
// ═══════════════════════════════════════════

export const getSymbols = () => api.get('/symbols')
export const getTradeHistory = (limit = 50, strategyId?: string) =>
  api.get('/trades/history', { params: { limit, strategy_id: strategyId } })
export const analyzePerpetual = (symbol: string) =>
  api.post('/perpetual-analysis', { symbol }, { timeout: PERPETUAL_ANALYSIS_TIMEOUT_MS })
export const getPerpetualAnalysisHistory = (params: any = {}) =>
  api.get('/perpetual-analysis/history', { params })
export const getPerpetualAnalysisHistoryDetail = (id: number | string) =>
  api.get(`/perpetual-analysis/history/${id}`)
export const updatePerpetualAnalysisHistory = (id: number | string, data: any) =>
  api.patch(`/perpetual-analysis/history/${id}`, data)
export const deletePerpetualAnalysisHistory = (id: number | string) =>
  api.delete(`/perpetual-analysis/history/${id}`)
export const getPerpetualAnalysisScoreSeries = (symbol: string, limit = 30) =>
  api.get('/perpetual-analysis/history/score-series', { params: { symbol, limit } })
export const replayPerpetualAnalysisHistory = (id: number | string, bar = '1H', limit = 100) =>
  api.get(`/perpetual-analysis/history/${id}/replay`, { params: { bar, limit } })

// ═══════════════════════════════════════════
// 系统配置
// ═══════════════════════════════════════════

export const getSettings = () => api.get('/settings')
export const updateSettings = (data: any) => api.put('/settings', data)
export const testAI = (data: any) => api.post('/settings/test-ai', data)
export const testOKX = (data: any) => api.post('/settings/test-okx', data)
export const testTelegram = (data: any) => api.post('/settings/test-telegram', data)

// ═══════════════════════════════════════════
// 健康检查
// ═══════════════════════════════════════════

export const healthCheck = () => api.get('/health')

export default api
