<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import { getStrategyPnl } from '../api'

const props = defineProps<{ strategyId: string }>()

const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

const pnlData = ref<any>(null)

async function loadData() {
  try {
    const { data } = await getStrategyPnl(props.strategyId)
    pnlData.value = data
    renderChart()
  } catch (e) {
    console.error('获取收益数据失败', e)
  }
}

function renderChart() {
  if (!chartRef.value || !pnlData.value) return

  if (!chart) {
    chart = echarts.init(chartRef.value, 'dark')
  }

  const points = pnlData.value.points || []

  if (points.length === 0) {
    chart.setOption({
      title: {
        text: '暂无交易数据',
        left: 'center',
        top: 'center',
        textStyle: { color: '#666', fontSize: 14 },
      },
    })
    return
  }

  const xData = points.map((p: any) => p.time)
  const yData = points.map((p: any) => p.pnl)

  const option: echarts.EChartsOption = {
    backgroundColor: 'transparent',
    grid: { top: 40, right: 24, bottom: 32, left: 60 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(20,20,30,0.9)',
      borderColor: '#333',
      textStyle: { color: '#e0e0e0', fontSize: 12 },
      formatter: (params: any) => {
        const p = params[0]
        const pt = points[p.dataIndex]
        return `
          <div style="font-size:11px;color:#888">${p.name}</div>
          <div>累计收益: <b style="color:${p.value >= 0 ? '#4ade80' : '#f87171'}">${p.value.toFixed(4)} USDT</b></div>
          <div>本笔: ${pt.trade_pnl >= 0 ? '+' : ''}${pt.trade_pnl.toFixed(4)} USDT</div>
          <div>${pt.symbol} ${pt.direction?.toUpperCase()}</div>
          <div style="font-size:10px;color:#888">最高: +${pt.peak_pnl.toFixed(4)} / 最低: ${pt.trough_pnl.toFixed(4)}</div>
        `
      },
    },
    xAxis: {
      type: 'category',
      data: xData,
      axisLabel: {
        fontSize: 10,
        color: '#888',
        formatter: (v: string) => v.slice(11, 16),
      },
      axisLine: { lineStyle: { color: '#333' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { fontSize: 10, color: '#888' },
      splitLine: { lineStyle: { color: '#222' } },
    },
    series: [
      {
        type: 'line',
        data: yData,
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { width: 2, color: '#818cf8' },
        itemStyle: {
          color: (params: any) => (params.value >= 0 ? '#4ade80' : '#f87171'),
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(129,140,248,0.3)' },
            { offset: 1, color: 'rgba(129,140,248,0.02)' },
          ]),
        },
        markLine: {
          silent: true,
          data: [{ yAxis: 0, lineStyle: { color: '#555', type: 'dashed' } }],
          label: { show: false },
        },
      },
    ],
  }

  chart.setOption(option, true)
}

const resizeHandler = () => chart?.resize()

onMounted(() => {
  loadData()
  window.addEventListener('resize', resizeHandler)
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeHandler)
  chart?.dispose()
  chart = null
})

watch(() => props.strategyId, loadData)
</script>

<template>
  <div class="pnl-chart-wrapper">
    <div class="pnl-stats" v-if="pnlData">
      <div class="pnl-stat">
        <span class="label">累计收益</span>
        <span class="value" :class="(pnlData.total_pnl || 0) >= 0 ? 'positive' : 'negative'">
          {{ (pnlData.total_pnl || 0) >= 0 ? '+' : '' }}{{ (pnlData.total_pnl || 0).toFixed(4) }} USDT
        </span>
      </div>
      <div class="pnl-stat">
        <span class="label">总交易</span>
        <span class="value">{{ pnlData.total_trades || 0 }}</span>
      </div>
      <div class="pnl-stat">
        <span class="label">胜率</span>
        <span class="value">{{ (pnlData.win_rate || 0).toFixed(1) }}%</span>
      </div>
      <div class="pnl-stat">
        <span class="label">最大回撤</span>
        <span class="value negative">{{ (pnlData.max_drawdown || 0).toFixed(4) }} USDT</span>
      </div>
    </div>
    <div ref="chartRef" class="chart-container" />
  </div>
</template>

<style scoped>
.pnl-chart-wrapper {
  background: var(--bg-card);
  border-radius: 12px;
  border: 1px solid var(--border);
  padding: 16px;
}
.pnl-stats {
  display: flex;
  gap: 24px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.pnl-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.pnl-stat .label {
  font-size: 11px;
  color: var(--text-muted);
}
.pnl-stat .value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.pnl-stat .value.positive { color: var(--accent-green); }
.pnl-stat .value.negative { color: var(--accent-red); }
.chart-container {
  width: 100%;
  height: 280px;
}
</style>
