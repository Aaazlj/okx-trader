<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts, type EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { ElMessage } from 'element-plus'
import {
  downloadBacktestCandles,
  getBacktestCandleCoverage,
  getMartingaleBacktestRecord,
  getMartingaleBacktestRecords,
  runMartingaleBacktest,
} from '../api'

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ strategy: any }>()

const chartRef = ref<HTMLElement>()
let chart: ECharts | null = null

const loading = ref(false)
const downloading = ref(false)
const coverageLoading = ref(false)
const recordsLoading = ref(false)
const result = ref<any>(null)
const coverage = ref<any>(null)
const records = ref<any[]>([])
const HOUR_MS = 60 * 60 * 1000
const dateRange = ref<[Date, Date]>([
  new Date(Date.now() - 7 * 24 * 60 * 60 * 1000),
  new Date(),
])
const form = ref({
  symbol: props.strategy.symbols?.[0] || 'BTC-USDT-SWAP',
  cycle: props.strategy.params?.cycle || 'medium',
})

function rangePayload() {
  return {
    symbol: form.value.symbol,
    cycle: form.value.cycle,
    start: dateRange.value?.[0]?.toISOString(),
    end: dateRange.value?.[1]?.toISOString(),
  }
}

function errorMessage(e: any, fallback: string) {
  const detail = e.response?.data?.detail
  if (typeof detail === 'string') return detail
  return fallback
}

async function loadCoverage() {
  if (!form.value.symbol || !dateRange.value?.[0] || !dateRange.value?.[1]) return
  coverageLoading.value = true
  try {
    const { data } = await getBacktestCandleCoverage(rangePayload())
    coverage.value = data
  } catch (e: any) {
    coverage.value = null
    ElMessage.error(errorMessage(e, '查询K线缓存失败'))
  } finally {
    coverageLoading.value = false
  }
}

async function downloadCandles() {
  if (!form.value.symbol || !dateRange.value?.[0] || !dateRange.value?.[1]) {
    ElMessage.warning('请选择下载时间范围')
    return
  }
  downloading.value = true
  try {
    const { data } = await downloadBacktestCandles(rangePayload())
    coverage.value = data.coverage
    ElMessage.success(`已保存 ${data.saved_count} 根K线`)
  } catch (e: any) {
    ElMessage.error(errorMessage(e, '下载K线失败'))
  } finally {
    downloading.value = false
  }
}

async function runBacktest() {
  loading.value = true
  try {
    const { data } = await runMartingaleBacktest({
      strategy_id: props.strategy.id,
      symbol: form.value.symbol,
      cycle: form.value.cycle,
      start: dateRange.value?.[0]?.toISOString(),
      end: dateRange.value?.[1]?.toISOString(),
      params: props.strategy.params,
      leverage: props.strategy.leverage,
      base_order_usdt: props.strategy.order_amount_usdt,
    })
    result.value = data
    await nextTick()
    renderChart()
    await loadRecords()
  } catch (e: any) {
    ElMessage.error(errorMessage(e, '回测失败'))
  } finally {
    loading.value = false
  }
}

async function loadRecords() {
  recordsLoading.value = true
  try {
    const { data } = await getMartingaleBacktestRecords({
      symbol: form.value.symbol,
      limit: 20,
    })
    records.value = data.items || []
  } catch (e: any) {
    ElMessage.error(errorMessage(e, '加载回测记录失败'))
  } finally {
    recordsLoading.value = false
  }
}

async function loadRecordDetail(id: number) {
  recordsLoading.value = true
  try {
    const { data } = await getMartingaleBacktestRecord(id)
    result.value = data.result
    await nextTick()
    renderChart()
  } catch (e: any) {
    ElMessage.error(errorMessage(e, '加载回测详情失败'))
  } finally {
    recordsLoading.value = false
  }
}

function renderChart() {
  if (!chartRef.value || !result.value) return
  if (!chart) chart = init(chartRef.value)

  const points = result.value.equity_curve || []
  const option: EChartsCoreOption = {
    backgroundColor: 'transparent',
    grid: { top: 18, right: 20, bottom: 30, left: 56 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.95)',
      borderColor: '#E8DFD5',
      textStyle: { color: '#2D2520', fontSize: 12 },
      formatter: (params: any) => {
        const p = params[0]
        const row = points[p.dataIndex]
        return `
          <div style="font-size:11px;color:#9C8E80">${row.time}</div>
          <div>权益: <b style="color:${row.equity >= 0 ? '#3A8A3A' : '#C44A3A'}">${row.equity.toFixed(4)} USDT</b></div>
          <div>已实现: ${row.realized.toFixed(4)} / 浮动: ${row.unrealized.toFixed(4)}</div>
        `
      },
    },
    xAxis: {
      type: 'category',
      data: points.map((p: any) => p.time),
      axisLabel: { fontSize: 10, color: '#9C8E80', formatter: (v: string) => v.slice(11, 16) },
      axisLine: { lineStyle: { color: '#E8DFD5' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { fontSize: 10, color: '#9C8E80' },
      splitLine: { lineStyle: { color: '#F0EBE3' } },
    },
    series: [
      {
        type: 'line',
        data: points.map((p: any) => p.equity),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color: '#C49060' },
      },
    ],
  }
  chart.setOption(option, true)
}

function formatTime(t: string) {
  if (!t) return '-'
  return t.replace('T', ' ').slice(0, 19)
}

function cycleLabel(cycle: string) {
  if (cycle === 'short') return '短期'
  if (cycle === 'long') return '长期'
  return '中期'
}

function coverageStatus() {
  if (!coverage.value) return '未查询缓存'
  if (coverage.value.is_sufficient) return `可回测：已缓存 ${coverage.value.cached_count} / 预计 ${coverage.value.expected_count} 根`
  return coverage.value.missing_reason || `缓存不足：已缓存 ${coverage.value.cached_count} 根`
}

function currentHourStart() {
  const end = new Date()
  end.setMinutes(0, 0, 0)
  return end
}

function setQuickRangeHours(hours: number) {
  const end = currentHourStart()
  dateRange.value = [
    new Date(end.getTime() - hours * HOUR_MS),
    end,
  ]
}

function setQuickRange(days: number) {
  setQuickRangeHours(days * 24)
}

const resizeHandler = () => chart?.resize()

onMounted(() => {
  window.addEventListener('resize', resizeHandler)
  loadCoverage()
  loadRecords()
})
onUnmounted(() => {
  window.removeEventListener('resize', resizeHandler)
  chart?.dispose()
  chart = null
})

watch(() => props.strategy.id, () => {
  result.value = null
  coverage.value = null
  form.value.symbol = props.strategy.symbols?.[0] || 'BTC-USDT-SWAP'
  form.value.cycle = props.strategy.params?.cycle || 'medium'
  loadRecords()
})

watch([() => form.value.symbol, () => form.value.cycle], () => {
  result.value = null
  coverage.value = null
  loadRecords()
})
</script>

<template>
  <div class="section martingale-backtest">
    <h3>马丁格尔回测</h3>
    <div class="backtest-controls">
      <label class="control-field">
        <span>交易对</span>
        <el-select v-model="form.symbol" filterable placeholder="交易对">
          <el-option
            v-for="sym in strategy.symbols"
            :key="sym"
            :label="sym"
            :value="sym"
          />
        </el-select>
      </label>
      <label class="control-field">
        <span>周期</span>
        <el-select v-model="form.cycle" placeholder="周期">
          <el-option label="短期" value="short" />
          <el-option label="中期" value="medium" />
          <el-option label="长期" value="long" />
        </el-select>
      </label>
      <label class="control-field range-field">
        <span>回测时间范围</span>
        <el-date-picker
          v-model="dateRange"
          type="datetimerange"
          start-placeholder="开始"
          end-placeholder="结束"
        />
      </label>
    </div>
    <div class="quick-ranges">
      <el-button size="small" @click="setQuickRangeHours(4)">近4h</el-button>
      <el-button size="small" @click="setQuickRangeHours(8)">近8h</el-button>
      <el-button size="small" @click="setQuickRangeHours(12)">近12h</el-button>
      <el-button size="small" @click="setQuickRange(1)">近1天</el-button>
      <el-button size="small" @click="setQuickRange(3)">近3天</el-button>
      <el-button size="small" @click="setQuickRange(7)">近7天</el-button>
      <el-button size="small" @click="setQuickRange(30)">近30天</el-button>
      <el-button size="small" @click="setQuickRange(90)">近90天</el-button>
    </div>
    <div class="backtest-actions">
      <el-button :loading="coverageLoading" @click="loadCoverage">查询缓存</el-button>
      <el-button :loading="downloading" @click="downloadCandles">下载K线</el-button>
      <el-button type="primary" :loading="loading" @click="runBacktest">运行回测</el-button>
    </div>

    <div class="coverage-row" :class="{ ok: coverage?.is_sufficient, warning: coverage && !coverage.is_sufficient }">
      <div>
        <b>K线缓存</b>
        <span>{{ coverageStatus() }}</span>
      </div>
      <div v-if="coverage" class="coverage-meta">
        {{ cycleLabel(coverage.cycle) }} · {{ coverage.bar }} ·
        {{ coverage.cached_start || '-' }} 至 {{ coverage.cached_end || '-' }}
      </div>
    </div>

    <div v-if="result?.summary" class="summary-grid">
      <div class="summary-item">
        <span>总收益</span>
        <b :class="result.summary.total_pnl >= 0 ? 'positive' : 'negative'">
          {{ result.summary.total_pnl >= 0 ? '+' : '' }}{{ result.summary.total_pnl }} USDT
        </b>
      </div>
      <div class="summary-item">
        <span>收益率</span>
        <b :class="result.summary.return_pct >= 0 ? 'positive' : 'negative'">
          {{ result.summary.return_pct >= 0 ? '+' : '' }}{{ result.summary.return_pct }}%
        </b>
      </div>
      <div class="summary-item">
        <span>最大回撤</span>
        <b class="negative">{{ result.summary.max_drawdown }} USDT</b>
      </div>
      <div class="summary-item">
        <span>胜率</span>
        <b>{{ result.summary.win_rate }}%</b>
      </div>
      <div class="summary-item">
        <span>交易数</span>
        <b>{{ result.summary.total_trades }}</b>
      </div>
      <div class="summary-item">
        <span>最大加仓</span>
        <b>{{ result.summary.max_add_count }}</b>
      </div>
      <div class="summary-item">
        <span>K线数量</span>
        <b>{{ result.summary.bar_count || result.candle_range?.candle_count || 0 }}</b>
      </div>
      <div v-if="result.record_id" class="summary-item">
        <span>记录ID</span>
        <b>#{{ result.record_id }}</b>
      </div>
    </div>

    <div v-if="result" ref="chartRef" class="chart-container" />

    <div v-if="result?.message" class="empty-tip">{{ result.message }}</div>
    <el-table
      v-if="result?.trades?.length"
      :data="result.trades"
      stripe
      size="small"
      class="dark-table"
    >
      <el-table-column label="开仓" width="160">
        <template #default="{ row }">{{ formatTime(row.entry_time) }}</template>
      </el-table-column>
      <el-table-column label="平仓" width="160">
        <template #default="{ row }">{{ formatTime(row.exit_time) }}</template>
      </el-table-column>
      <el-table-column prop="direction" label="方向" width="80" />
      <el-table-column label="加仓" width="70">
        <template #default="{ row }">{{ Math.max(0, row.levels - 1) }}</template>
      </el-table-column>
      <el-table-column prop="avg_price" label="均价" width="110" />
      <el-table-column prop="exit_price" label="出场价" width="110" />
      <el-table-column prop="liquidation_price" label="预估强平价" width="120" />
      <el-table-column label="盈亏" width="110">
        <template #default="{ row }">
          <span :class="row.pnl >= 0 ? 'positive' : 'negative'">
            {{ row.pnl >= 0 ? '+' : '' }}{{ row.pnl }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="fee" label="手续费" width="90" />
      <el-table-column prop="reason" label="原因" min-width="120" />
    </el-table>

    <div class="records-section">
      <div class="records-head">
        <h4>回测记录</h4>
        <el-button size="small" :loading="recordsLoading" @click="loadRecords">刷新</el-button>
      </div>
      <div v-if="!records.length" class="empty-tip">暂无回测记录</div>
      <el-table
        v-else
        :data="records"
        stripe
        size="small"
        class="dark-table"
      >
        <el-table-column prop="created_at" label="时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="symbol" label="交易对" width="140" />
        <el-table-column label="周期" width="80">
          <template #default="{ row }">{{ cycleLabel(row.cycle) }}</template>
        </el-table-column>
        <el-table-column label="范围" min-width="230">
          <template #default="{ row }">{{ formatTime(row.start) }} 至 {{ formatTime(row.end) }}</template>
        </el-table-column>
        <el-table-column label="收益" width="110">
          <template #default="{ row }">
            <span :class="row.total_pnl >= 0 ? 'positive' : 'negative'">
              {{ row.total_pnl >= 0 ? '+' : '' }}{{ row.total_pnl }} USDT
            </span>
          </template>
        </el-table-column>
        <el-table-column label="收益率" width="90">
          <template #default="{ row }">
            <span :class="row.return_pct >= 0 ? 'positive' : 'negative'">
              {{ row.return_pct >= 0 ? '+' : '' }}{{ row.return_pct }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="total_trades" label="交易数" width="80" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button size="small" text @click="loadRecordDetail(row.id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.martingale-backtest {
  padding: 20px;
}
.martingale-backtest h3 {
  font-family: var(--font-display);
  font-size: 15px;
  margin: 0 0 14px;
}
.backtest-controls {
  display: grid;
  grid-template-columns: minmax(150px, 1fr) 110px minmax(300px, 1.4fr);
  gap: 10px;
  align-items: center;
}
.control-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.control-field > span {
  color: var(--text-muted);
  font-size: 12px;
}
.range-field :deep(.el-date-editor) {
  width: 100%;
}
.quick-ranges {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.backtest-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 10px;
}
.coverage-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg-secondary);
  font-size: 12px;
  color: var(--text-secondary);
}
.coverage-row b {
  color: var(--text-primary);
  margin-right: 8px;
}
.coverage-row.ok {
  border-color: rgba(58, 138, 58, 0.35);
}
.coverage-row.warning {
  border-color: rgba(196, 74, 58, 0.35);
}
.coverage-meta {
  color: var(--text-muted);
  white-space: nowrap;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  margin-top: 16px;
}
.summary-item {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.summary-item span {
  font-size: 11px;
  color: var(--text-muted);
}
.summary-item b {
  font-size: 14px;
}
.chart-container {
  width: 100%;
  height: 280px;
  margin-top: 16px;
}
.records-section {
  margin-top: 18px;
}
.records-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.records-head h4 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}
.positive { color: var(--accent-green); }
.negative { color: var(--accent-red); }
.empty-tip {
  text-align: center;
  padding: 18px;
  color: var(--text-muted);
  font-size: 13px;
}
@media (max-width: 1100px) {
  .backtest-controls {
    grid-template-columns: 1fr 1fr;
  }
  .coverage-row {
    flex-direction: column;
  }
  .coverage-meta {
    white-space: normal;
  }
}
</style>
