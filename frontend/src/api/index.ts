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

// ═══════════════════════════════════════════
// 市场
// ═══════════════════════════════════════════

export const getSymbols = () => api.get('/symbols')
export const getTradeHistory = (limit = 50, strategyId?: string) =>
  api.get('/trades/history', { params: { limit, strategy_id: strategyId } })

// ═══════════════════════════════════════════
// 健康检查
// ═══════════════════════════════════════════

export const healthCheck = () => api.get('/health')

export default api
