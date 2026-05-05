<script setup lang="ts">
import { ref, computed, defineAsyncComponent, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useTradingStore } from '../stores/trading'
import MartingaleBacktest from '../components/MartingaleBacktest.vue'
import ContractGridBacktest from '../components/ContractGridBacktest.vue'
import {
  getStrategy,
  getStrategyPositions,
  getStrategySignals,
  getTradeHistory,
  startStrategy,
  stopStrategy,
} from '../api'

const route = useRoute()
const store = useTradingStore()
const PnlChart = defineAsyncComponent(() => import('../components/PnlChart.vue'))

const strategyId = computed(() => route.params.id as string)
const strategy = ref<any>(null)
const positions = ref<any[]>([])
const signals = ref<any[]>([])
const trades = ref<any[]>([])
const loading = ref(true)
const toggling = ref(false)
const showPrompt = ref(false)

// 策略对应的实时日志
const liveLogs = computed(() => store.strategyLogs[strategyId.value] || [])
const isMartingale = computed(() => strategy.value?.strategy_type === 'martingale_contract')
const isContractGrid = computed(() => strategy.value?.strategy_type === 'contract_grid')

async function loadAll(initial = false) {
  if (initial) loading.value = true
  try {
    const [sRes, pRes, sigRes, tRes] = await Promise.allSettled([
      getStrategy(strategyId.value),
      getStrategyPositions(strategyId.value),
      getStrategySignals(strategyId.value, 100),
      getTradeHistory(100, strategyId.value),
    ])
    if (sRes.status === 'fulfilled') strategy.value = sRes.value.data
    if (pRes.status === 'fulfilled') positions.value = pRes.value.data
    if (sigRes.status === 'fulfilled') signals.value = sigRes.value.data
    if (tRes.status === 'fulfilled') trades.value = tRes.value.data
  } catch (e) {
    console.error('加载策略详情失败', e)
  }
  loading.value = false
}

async function toggleActive() {
  if (!strategy.value) return
  if (isContractGrid.value) {
    ElMessage.warning('合约网格 v1 仅支持参数配置和回测，暂不支持实盘启动')
    return
  }
  toggling.value = true
  try {
    if (strategy.value.is_active) {
      await stopStrategy(strategyId.value)
      ElMessage.warning(`策略已暂停`)
    } else {
      await startStrategy(strategyId.value)
      ElMessage.success(`策略已启动`)
    }
    const { data } = await getStrategy(strategyId.value)
    strategy.value = data
    await store.fetchStrategies()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
  toggling.value = false
}

function formatTime(t: string) {
  if (!t) return '-'
  return t.replace('T', ' ').slice(0, 19)
}

function directionLabel(d: string) {
  if (d === 'long') return '🟢 做多'
  if (d === 'short') return '🔴 做空'
  return d
}

function signalResultLabel(r: string) {
  if (r === 'signal') return '✅ 触发'
  if (r === 'idle') return '⏸ 无信号'
  if (r === 'error') return '❌ 错误'
  return r
}

function tradeDuration(entry: string, exit: string) {
  if (!entry || !exit) return '-'
  const ms = new Date(exit).getTime() - new Date(entry).getTime()
  if (ms < 0) return '-'
  const mins = Math.floor(ms / 60000)
  if (mins < 60) return `${mins}m`
  const h = Math.floor(mins / 60)
  return `${h}h${mins % 60}m`
}

function formatDuration(seconds: number) {
  if (!seconds || seconds <= 0) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h${m}m`
  return `${m}m`
}

function pnlPercent(row: any) {
  return row.pnl_ratio ?? null
}

function cycleLabel(cycle: string) {
  if (cycle === 'short') return '短期'
  if (cycle === 'long') return '长期'
  return '中期'
}

function unitLabel(type: string) {
  return type === 'usdt' ? 'U' : '%'
}

function gridModeLabel(mode: string) {
  if (mode === 'long') return '多网格'
  if (mode === 'short') return '空网格'
  return '中性网格'
}

function formatNumber(value: any, digits = 3) {
  const num = Number(value)
  return Number.isFinite(num) ? num.toFixed(digits) : '-'
}

const martingaleParamItems = computed(() => {
  const p = strategy.value?.params || {}
  return [
    {
      label: '周期',
      value: `${cycleLabel(p.cycle || 'medium')} (${p.bar || '4H'})`,
      desc: '短期=1H，中期=4H，长期=1D',
    },
    {
      label: '方向',
      value: p.direction === 'both' ? '双向' : p.direction === 'short' ? '只做空' : '只做多',
      desc: '限制首单信号方向',
    },
    {
      label: '跌/涨加仓',
      value: `${p.add_trigger_value ?? p.price_step_pct ?? '-'} ${unitLabel(p.add_trigger_type || 'pct')}`,
      desc: unitLabel(p.add_trigger_type) === 'U'
        ? '做多下跌、做空上涨达到该 USDT 价格差后加仓'
        : '做多下跌、做空上涨达到该百分比后加仓',
    },
    {
      label: '周期止盈',
      value: `${p.take_profit_value ?? p.take_profit_pct ?? '-'} ${unitLabel(p.take_profit_type || 'pct')}`,
      desc: unitLabel(p.take_profit_type) === 'U'
        ? '本轮持仓浮盈达到该 USDT 金额后平仓'
        : '本轮持仓相对均价达到该收益比例后平仓',
    },
    {
      label: '投资额',
      value: `${p.max_position_usdt ?? '-'} USDT`,
      desc: '自动计算：初次保证金 + 加仓保证金 × 最大自动加仓次数',
    },
    {
      label: '初次保证金',
      value: `${p.initial_margin_usdt ?? '-'} USDT`,
      desc: '首单保证金',
    },
    {
      label: '加仓保证金',
      value: `${p.add_margin_usdt ?? '-'} USDT`,
      desc: '每次自动加仓单保证金',
    },
    {
      label: '最大自动加仓',
      value: `${p.max_add_count ?? 0} 次`,
      desc: '首单之后最多自动加仓次数',
    },
    {
      label: '杠杆',
      value: `${strategy.value?.leverage || 1}x`,
      desc: '合约杠杆倍数',
    },
  ]
})

const contractGridParamItems = computed(() => {
  const p = strategy.value?.params || {}
  return [
    {
      label: '周期',
      value: `${cycleLabel(p.cycle || 'medium')} (${p.bar || '1H'})`,
      desc: '短期=15m，中期=1H，长期=4H',
    },
    {
      label: '网格方向',
      value: gridModeLabel(p.grid_mode || 'neutral'),
      desc: '中性 / 多网格 / 空网格均可回测',
    },
    {
      label: '价格区间',
      value: `${p.lower_price || '-'} - ${p.upper_price || '-'}`,
      desc: '价格触达区间内网格线时模拟开平仓',
    },
    {
      label: '网格数量',
      value: `${p.grid_count || 0} 格`,
      desc: `每格约 ${formatNumber(p.grid_spacing_pct || 0)}%`,
    },
    {
      label: '保证金预算',
      value: `${p.total_margin_usdt || '-'} USDT`,
      desc: '按网格数量等额分配，受总预算约束',
    },
    {
      label: '杠杆',
      value: `${strategy.value?.leverage || p.leverage || 1}x`,
      desc: '仅用于回测盈亏估算',
    },
    {
      label: '区间失效',
      value: `${p.stop_lower_price || '-'} / ${p.stop_upper_price || '-'}`,
      desc: '跌破下沿或突破上沿后停止回测并结算',
    },
    {
      label: '成本',
      value: `${p.fee_rate ?? 0.0005} fee / ${p.slippage_pct ?? 0.02}% slip`,
      desc: '手续费率和滑点参数',
    },
  ]
})

onMounted(() => loadAll(true))
watch(strategyId, () => loadAll(true))

// 定时刷新
let timer: number
onMounted(() => {
  timer = window.setInterval(loadAll, 15000)
})
import { onUnmounted } from 'vue'
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="strategy-detail" v-if="strategy" v-loading="loading">
    <!-- ① 策略概览 -->
    <div class="section overview-section">
      <div class="overview-header">
        <div>
          <h2 class="strategy-title">
            <span class="status-dot" :class="strategy.is_active ? 'running' : 'stopped'" />
            {{ strategy.name }}
          </h2>
          <div class="overview-meta">
            <el-tag size="small" :type="strategy.decision_mode === 'ai' ? 'warning' : strategy.decision_mode === 'hybrid' ? 'success' : 'info'" effect="dark">
              {{ strategy.decision_mode === 'ai' ? '🤖 AI 驱动' : strategy.decision_mode === 'hybrid' ? '🔀 混合模式' : '📐 技术指标' }}
            </el-tag>
            <el-tag size="small" effect="plain">{{ strategy.leverage }}x</el-tag>
            <el-tag size="small" effect="plain">{{ strategy.order_amount_usdt }} USDT</el-tag>
            <el-tag size="small" effect="plain">{{ strategy.mgn_mode }}</el-tag>
            <el-tag size="small" effect="plain">间隔 {{ strategy.poll_interval }}s</el-tag>
          </div>
        </div>
        <div style="display: flex; gap: 8px">
          <el-button
            :type="strategy.is_active ? 'danger' : 'success'"
            :loading="toggling"
            @click="toggleActive"
          >
            {{ isContractGrid ? '仅支持回测' : strategy.is_active ? '暂停策略' : '启动策略' }}
          </el-button>
        </div>
      </div>
      <div class="symbols-row">
        <span class="label">交易对</span>
        <div class="symbols-tags">
          <span v-for="sym in strategy.symbols" :key="sym" class="symbol-tag">
            {{ sym.replace('-USDT-SWAP', '') }}
          </span>
        </div>
      </div>
    </div>

    <!-- ② 收益图表 -->
    <div class="section">
      <h3>📈 收益曲线</h3>
      <PnlChart :strategy-id="strategyId" />
    </div>

    <!-- ③ AI Prompt / 策略参数 -->
    <div class="section">
      <h3>{{ (strategy.decision_mode === 'ai' || strategy.decision_mode === 'hybrid') ? '🤖 AI Prompt 与参数' : '⚙️ 策略参数' }}</h3>
      <div class="params-content">
        <template v-if="strategy.decision_mode === 'ai' || strategy.decision_mode === 'hybrid'">
          <div class="ai-confidence">
            <span>最低置信度: </span>
            <el-tag type="warning" effect="dark">{{ strategy.ai_min_confidence }}%</el-tag>
          </div>
          <div class="prompt-block">
            <div class="prompt-toggle" @click="showPrompt = !showPrompt">
              <span>{{ showPrompt ? '▼' : '▶' }} AI Prompt</span>
              <span style="font-size: 11px; color: var(--text-muted)">
                {{ strategy.ai_prompt?.length || 0 }} 字符
              </span>
            </div>
            <pre v-show="showPrompt" class="prompt-text">{{ strategy.ai_prompt || '（未配置）' }}</pre>
          </div>
        </template>
        <div v-if="isMartingale" class="martingale-param-grid">
          <div v-for="item in martingaleParamItems" :key="item.label" class="martingale-param-item">
            <div class="martingale-param-top">
              <span class="param-key">{{ item.label }}</span>
              <span class="param-val">{{ item.value }}</span>
            </div>
            <div class="param-desc">{{ item.desc }}</div>
          </div>
        </div>
        <div v-else-if="isContractGrid" class="martingale-param-grid">
          <div v-for="item in contractGridParamItems" :key="item.label" class="martingale-param-item">
            <div class="martingale-param-top">
              <span class="param-key">{{ item.label }}</span>
              <span class="param-val">{{ item.value }}</span>
            </div>
            <div class="param-desc">{{ item.desc }}</div>
          </div>
        </div>
        <div v-else class="params-grid">
          <div v-for="(val, key) in strategy.params" :key="key" class="param-item">
            <span class="param-key">{{ key }}</span>
            <span class="param-val">{{ val }}</span>
          </div>
        </div>
      </div>
    </div>

    <MartingaleBacktest
      v-if="strategy.strategy_type === 'martingale_contract'"
      :strategy="strategy"
    />
    <ContractGridBacktest
      v-if="strategy.strategy_type === 'contract_grid'"
      :strategy="strategy"
    />

    <!-- ④ 策略持仓 -->
    <div class="section">
      <h3>📊 策略持仓 <span class="count-badge">{{ positions.length }}</span></h3>
      <div v-if="positions.length === 0" class="empty-tip">暂无持仓</div>
      <el-table v-else :data="positions" stripe size="small" class="dark-table">
        <el-table-column prop="symbol" label="交易对" width="160">
          <template #default="{ row }">{{ row.symbol?.replace('-USDT-SWAP', '') }}</template>
        </el-table-column>
        <el-table-column label="方向" width="100">
          <template #default="{ row }">
            <span :class="row.direction === 'long' ? 'positive' : 'negative'">
              {{ directionLabel(row.direction) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="entry_price" label="入场价" width="120" />
        <el-table-column label="现价" width="120">
          <template #default="{ row }">{{ (row.current_price || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="quantity" label="数量" width="80" />
        <el-table-column label="最高盈亏" width="120">
          <template #default="{ row }">
            <span class="positive">+{{ (row.peak_pnl || 0).toFixed(4) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最低盈亏" width="120">
          <template #default="{ row }">
            <span class="negative">{{ (row.trough_pnl || 0).toFixed(4) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="tp_price" label="止盈" width="100" />
        <el-table-column label="TP距离" width="80">
          <template #default="{ row }">
            <span v-if="row.tp_distance_pct !== null" style="color: var(--accent-green)">
              {{ row.tp_distance_pct > 0 ? '+' : '' }}{{ row.tp_distance_pct }}%
            </span>
            <span v-else style="color: var(--text-muted)">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="sl_price" label="止损" width="100" />
        <el-table-column prop="liquidation_price" label="强平价" width="110">
          <template #default="{ row }">{{ row.liquidation_price || '-' }}</template>
        </el-table-column>
        <el-table-column label="SL距离" width="80">
          <template #default="{ row }">
            <span v-if="row.sl_distance_pct !== null" style="color: var(--accent-red)">
              {{ row.sl_distance_pct > 0 ? '+' : '' }}{{ row.sl_distance_pct }}%
            </span>
            <span v-else style="color: var(--text-muted)">-</span>
          </template>
        </el-table-column>
        <el-table-column label="时长" width="80">
          <template #default="{ row }">
            <span style="color: var(--text-muted)">{{ formatDuration(row.holding_seconds) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="open_time" label="开仓时间" width="170">
          <template #default="{ row }">{{ formatTime(row.open_time) }}</template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ⑤ 信号与 AI 分析日志 -->
    <div class="section">
      <h3>📡 信号监控 <span class="count-badge">{{ signals.length + liveLogs.length }}</span></h3>

      <!-- 实时 WebSocket 推送 -->
      <div v-if="liveLogs.length > 0" class="live-logs">
        <div class="sub-title">🔴 实时推送</div>
        <div v-for="(log, idx) in liveLogs.slice(0, 20)" :key="idx" class="log-line" :class="log.type">
          <span class="log-time">{{ log.time }}</span>
          <span class="log-msg">{{ log.message }}</span>
        </div>
      </div>

      <!-- 历史信号 -->
      <div class="sub-title" style="margin-top: 12px">📋 历史信号记录</div>
      <div v-if="signals.length === 0" class="empty-tip">暂无信号记录</div>
      <el-table v-else :data="signals.slice(0, 50)" stripe size="small" class="dark-table">
        <el-table-column prop="created_at" label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="symbol" label="交易对" width="140">
          <template #default="{ row }">{{ row.symbol?.replace('-USDT-SWAP', '') }}</template>
        </el-table-column>
        <el-table-column label="结果" width="100">
          <template #default="{ row }">{{ signalResultLabel(row.result) }}</template>
        </el-table-column>
        <el-table-column label="方向" width="90">
          <template #default="{ row }">
            <span v-if="row.direction && row.direction !== 'idle'"
                  :class="row.direction === 'long' ? 'positive' : 'negative'">
              {{ row.direction?.toUpperCase() }}
            </span>
            <span v-else style="color: var(--text-muted)">—</span>
          </template>
        </el-table-column>
        <el-table-column label="置信度" width="80" v-if="strategy.decision_mode === 'ai' || strategy.decision_mode === 'hybrid'">
          <template #default="{ row }">{{ row.confidence || '-' }}%</template>
        </el-table-column>
        <el-table-column label="分析理由" min-width="200">
          <template #default="{ row }">
            <span class="reasoning-text">{{ row.reasoning || '-' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ⑥ 交易历史 -->
    <div class="section">
      <h3>📜 交易历史 <span class="count-badge">{{ trades.length }}</span></h3>
      <div v-if="trades.length === 0" class="empty-tip">暂无交易记录</div>
      <el-table v-else :data="trades" stripe size="small" class="dark-table">
        <el-table-column prop="entry_time" label="开仓时间" width="170">
          <template #default="{ row }">{{ formatTime(row.entry_time) }}</template>
        </el-table-column>
        <el-table-column prop="symbol" label="交易对" width="130">
          <template #default="{ row }">{{ row.symbol?.replace('-USDT-SWAP', '') }}</template>
        </el-table-column>
        <el-table-column label="方向" width="90">
          <template #default="{ row }">
            <span :class="row.direction === 'long' ? 'positive' : 'negative'">
              {{ directionLabel(row.direction) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="entry_price" label="入场价" width="100" />
        <el-table-column prop="exit_price" label="出场价" width="100">
          <template #default="{ row }">{{ row.exit_price || '-' }}</template>
        </el-table-column>
        <el-table-column label="盈亏" width="110">
          <template #default="{ row }">
            <span :class="(row.pnl || 0) >= 0 ? 'positive' : 'negative'">
              {{ (row.pnl || 0) >= 0 ? '+' : '' }}{{ (row.pnl || 0).toFixed(4) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="盈亏%" width="80">
          <template #default="{ row }">
            <span v-if="pnlPercent(row) !== null"
                  :class="(row.pnl || 0) >= 0 ? 'positive' : 'negative'">
              {{ (row.pnl || 0) >= 0 ? '+' : '' }}{{ pnlPercent(row) }}%
            </span>
            <span v-else style="color: var(--text-muted)">-</span>
          </template>
        </el-table-column>
        <el-table-column label="手续费" width="80">
          <template #default="{ row }">
            <span style="color: var(--text-muted)">{{ (row.fee || 0).toFixed(4) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="时长" width="80">
          <template #default="{ row }">
            <span style="color: var(--text-muted)">{{ tradeDuration(row.entry_time, row.exit_time) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最高盈亏" width="110">
          <template #default="{ row }">
            <span class="positive">+{{ (row.peak_pnl || 0).toFixed(4) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最低盈亏" width="110">
          <template #default="{ row }">
            <span class="negative">{{ (row.trough_pnl || 0).toFixed(4) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="exit_time" label="平仓时间" width="170">
          <template #default="{ row }">{{ formatTime(row.exit_time) }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="160">
          <template #default="{ row }">
            <span class="reasoning-text">{{ row.reason || '-' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>

  <div v-else-if="loading" class="loading-wrapper" v-loading="true" style="min-height: 400px" />
  <div v-else class="empty-tip" style="padding: 60px; text-align: center">策略不存在</div>
</template>

<style scoped>
.strategy-detail {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.section {
  background: var(--bg-card);
  border-radius: 12px;
  border: 1px solid var(--border);
  padding: 20px;
}
.section h3 {
  font-family: var(--font-display);
  font-size: 15px;
  margin: 0 0 14px;
  color: var(--text-primary);
  font-weight: 600;
}
.overview-section {
  padding: 24px;
}
.overview-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.strategy-title {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 600;
  margin: 0 0 8px;
  display: flex;
  align-items: center;
  gap: 10px;
  letter-spacing: -0.02em;
}
.overview-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.symbols-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.symbols-row .label {
  font-size: 12px;
  color: var(--text-muted);
}
.symbols-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.symbol-tag {
  background: var(--bg-secondary);
  color: var(--text-primary);
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}
.count-badge {
  background: var(--bg-secondary);
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 400;
}

/* ====== params ====== */
.params-content { display: flex; flex-direction: column; gap: 12px; }
.ai-confidence { font-size: 13px; color: var(--text-secondary); }
.prompt-block { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.prompt-toggle {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 12px; cursor: pointer; background: var(--bg-secondary);
  font-size: 13px; color: var(--text-primary);
}
.prompt-toggle:hover { background: var(--bg-hover); }
.prompt-text {
  padding: 12px; font-size: 11px; line-height: 1.6;
  font-family: var(--font-mono);
  color: var(--text-secondary); white-space: pre-wrap; word-break: break-all;
  max-height: 400px; overflow-y: auto; margin: 0;
  background: var(--bg-primary);
}
.params-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 6px;
}
.martingale-param-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.param-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 4px 10px; background: var(--bg-secondary); border-radius: 6px; font-size: 12px;
}
.martingale-param-item {
  padding: 8px 10px;
  background: var(--bg-secondary);
  border-radius: 6px;
}
.martingale-param-top {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
}
.param-desc {
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.35;
}
.param-key { color: var(--text-muted); }
.param-val { color: var(--text-primary); font-weight: 500; }

/* ====== signals ====== */
.sub-title { font-size: 13px; color: var(--text-muted); margin-bottom: 8px; }
.live-logs { margin-bottom: 12px; }
.log-line {
  display: flex; gap: 12px; padding: 4px 8px; font-size: 12px;
  border-radius: 4px; margin-bottom: 2px;
}
.log-line.signal { background: rgba(184,122,48,0.06); }
.log-line.trade  { background: rgba(58,138,58,0.06); }
.log-line.error  { background: rgba(196,74,58,0.06); }
.log-time { color: var(--text-muted); white-space: nowrap; }
.log-msg  { color: var(--text-primary); }
.reasoning-text {
  font-size: 11px; color: var(--text-secondary); max-width: 300px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block;
}

.empty-tip {
  text-align: center; padding: 24px; color: var(--text-muted); font-size: 13px;
}
.positive { color: var(--accent-green); }
.negative { color: var(--accent-red); }

.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.status-dot.running { background: var(--accent-green); box-shadow: 0 0 6px var(--accent-green); }
.status-dot.stopped { background: var(--text-muted); }

.dark-table :deep(.el-table) { background: transparent; }
</style>
