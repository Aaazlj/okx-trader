<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { analyzePerpetual } from '../api'
import PerpetualAnalysisReport from '../components/PerpetualAnalysisReport.vue'
import { useTradingStore } from '../stores/trading'

const store = useTradingStore()
const router = useRouter()

const defaultSymbols = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP']
const selectedSymbol = ref('BTC-USDT-SWAP')
const analysis = ref<any>(null)
const loading = ref(false)
const progress = ref(0)
const progressText = ref('')
let progressTimer: number | undefined

const symbolOptions = computed(() => {
  const fromStore = store.symbols.map((item: any) => item.inst_id).filter(Boolean)
  return Array.from(new Set([...defaultSymbols, ...fromStore]))
})

onMounted(() => {
  if (store.symbols.length === 0) {
    store.fetchSymbols()
  }
})

async function startAnalysis() {
  const symbol = selectedSymbol.value.trim().toUpperCase()
  if (!symbol) {
    ElMessage.warning('请输入交易对')
    return
  }

  loading.value = true
  analysis.value = null
  progress.value = 8
  progressText.value = '拉取 OKX 数据'
  startProgress()

  try {
    const { data } = await analyzePerpetual(symbol)
    analysis.value = data
    progress.value = 100
    progressText.value = data.ai_report ? '分析完成' : '结构化分析完成'
    if (data.ai_report_error) {
      ElMessage.warning(data.ai_report_error)
    } else if (data.history_id) {
      ElMessage.success('分析完成，已保存历史记录')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '数据加载失败，请重试')
  } finally {
    stopProgress()
    loading.value = false
  }
}

function startProgress() {
  const steps = ['拉取 OKX 数据', '计算技术指标', '生成结构化报告', 'AI 生成报告']
  let idx = 0
  progressTimer = window.setInterval(() => {
    idx = Math.min(idx + 1, steps.length - 1)
    progressText.value = steps[idx]
    progress.value = Math.min(progress.value + 18, 88)
  }, 850)
}

function stopProgress() {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = undefined
  }
}
</script>

<template>
  <div class="analysis-page">
    <div class="analysis-toolbar">
      <div class="symbol-control">
        <label>交易对</label>
        <el-select
          v-model="selectedSymbol"
          filterable
          allow-create
          default-first-option
          placeholder="BTC-USDT-SWAP"
        >
          <el-option
            v-for="symbol in symbolOptions"
            :key="symbol"
            :label="symbol"
            :value="symbol"
          />
        </el-select>
      </div>
      <div>
        <el-button type="primary" :loading="loading" @click="startAnalysis">
          <el-icon><DataAnalysis /></el-icon>
          开始分析
        </el-button>
        <el-button @click="router.push('/analysis/history')">
          <el-icon><Clock /></el-icon>
          历史记录
        </el-button>
      </div>
    </div>

    <div v-if="loading" class="progress-line">
      <span>{{ progressText }}</span>
      <el-progress :percentage="progress" :stroke-width="8" />
    </div>

    <PerpetualAnalysisReport v-if="analysis" :analysis="analysis" />
  </div>
</template>

<style scoped>
.analysis-page {
  max-width: 1440px;
  margin: 0 auto;
  padding: 24px 28px 64px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.analysis-toolbar {
  display: flex;
  align-items: end;
  gap: 12px;
  padding: 18px 20px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}

.symbol-control {
  width: min(460px, 100%);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.symbol-control label {
  font-size: 12px;
  color: var(--text-muted);
}

.progress-line {
  padding: 14px 18px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  display: grid;
  gap: 8px;
}

@media (max-width: 640px) {
  .analysis-page {
    padding: 12px;
  }

  .analysis-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
