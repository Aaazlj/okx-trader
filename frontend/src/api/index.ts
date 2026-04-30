import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

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

// ═══════════════════════════════════════════
// 市场
// ═══════════════════════════════════════════

export const getSymbols = () => api.get('/symbols')
export const getTradeHistory = (limit = 50, strategyId?: string) =>
  api.get('/trades/history', { params: { limit, strategy_id: strategyId } })

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
