<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  deletePerpetualAnalysisHistory,
  getPerpetualAnalysisHistoryDetail,
  getPerpetualAnalysisScoreSeries,
  replayPerpetualAnalysisHistory,
  updatePerpetualAnalysisHistory,
} from '../api'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import PerpetualAnalysisReport from '../components/PerpetualAnalysisReport.vue'

const route = useRoute()
const router = useRouter()

const record = ref<any>(null)
const scoreSeries = ref<any[]>([])
const replay = ref<any>(null)
const loading = ref(true)
const saving = ref(false)
const deleting = ref(false)
const deleteDialogVisible = ref(false)
const replayLoading = ref(false)
const noteDraft = ref('')
const replayBar = ref('1H')

const snapshot = computed(() => record.value?.snapshot || null)
const priceComparison = computed(() => record.value?.price_comparison || {})

onMounted(() => {
  loadDetail()
})

async function loadDetail() {
  loading.value = true
  try {
    const { data } = await getPerpetualAnalysisHistoryDetail(route.params.id as string)
    record.value = data
    noteDraft.value = data.note || ''
    await loadScoreSeries(data.symbol)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '历史详情加载失败')
  } finally {
    loading.value = false
  }
}

async function loadScoreSeries(symbol: string) {
  const { data } = await getPerpetualAnalysisScoreSeries(symbol, 50)
  scoreSeries.value = data.items || []
}

async function saveNote() {
  if (!record.value) return
  saving.value = true
  try {
    const { data } = await updatePerpetualAnalysisHistory(record.value.id, {
      note: noteDraft.value,
    })
    record.value = { ...record.value, ...data }
    noteDraft.value = data.note || ''
    ElMessage.success('备注已保存')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

function requestDelete() {
  if (!record.value) return
  deleteDialogVisible.value = true
}

async function confirmDelete() {
  if (!record.value) return

  deleting.value = true
  try {
    await deletePerpetualAnalysisHistory(record.value.id)
    ElMessage.success('历史记录已删除')
    deleteDialogVisible.value = false
    router.push('/analysis/history')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  } finally {
    deleting.value = false
  }
}

async function runReplay() {
  replayLoading.value = true
  try {
    const { data } = await replayPerpetualAnalysisHistory(route.params.id as string, replayBar.value, 120)
    replay.value = data
    if (!data.candles?.length) {
      ElMessage.warning('未获取到分析时间点后的 K 线')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '复盘加载失败')
  } finally {
    replayLoading.value = false
  }
}

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  if (value >= 100) return value.toLocaleString('en-US', { maximumFractionDigits: 2 })
  if (value >= 1) return value.toLocaleString('en-US', { maximumFractionDigits: 4 })
  return value.toLocaleString('en-US', { maximumFractionDigits: 8 })
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function scoreClass(change: number | null | undefined) {
  if (change === null || change === undefined || change === 0) return ''
  return change > 0 ? 'positive' : 'negative'
}
</script>

<template>
  <div class="history-detail" v-loading="loading">
    <div class="detail-toolbar">
      <el-button circle @click="router.push('/analysis/history')">
        <el-icon><ArrowLeft /></el-icon>
      </el-button>
      <div class="toolbar-title">
        <span class="eyebrow">Analysis History</span>
        <h2>{{ record?.symbol || '-' }}</h2>
      </div>
      <div class="toolbar-actions">
        <el-button type="danger" :disabled="deleting" @click="requestDelete">删除</el-button>
        <el-button type="primary" @click="router.push('/analysis')">新分析</el-button>
      </div>
    </div>

    <template v-if="record && snapshot">
      <section class="history-tools">
        <div class="price-compare">
          <div class="metric">
            <span>分析时价格</span>
            <strong>{{ formatPrice(priceComparison.analysis_price) }}</strong>
          </div>
          <div class="metric">
            <span>当前实时价</span>
            <strong>{{ formatPrice(priceComparison.current_price) }}</strong>
          </div>
          <div class="metric">
            <span>价格变化</span>
            <strong :class="scoreClass(priceComparison.price_delta)">
              {{ formatPrice(priceComparison.price_delta) }} / {{ formatPct(priceComparison.price_delta_pct) }}
            </strong>
          </div>
        </div>
        <div class="note-box">
          <div class="section-header">
            <h2>备注</h2>
            <span>复盘结论或人工标注</span>
          </div>
          <el-input
            v-model="noteDraft"
            type="textarea"
            :rows="3"
            maxlength="2000"
            show-word-limit
            placeholder="记录后续观察、复盘结论或交易计划调整"
          />
          <div class="note-actions">
            <el-button type="primary" :loading="saving" @click="saveNote">保存备注</el-button>
          </div>
        </div>
      </section>

      <PerpetualAnalysisReport :analysis="snapshot" />

      <section class="section">
        <div class="section-header">
          <h2>评分变化对比</h2>
          <span>{{ record.symbol }} 最近 {{ scoreSeries.length }} 次分析</span>
        </div>
        <el-table :data="scoreSeries" stripe size="small">
          <el-table-column prop="created_at" label="时间" width="170" />
          <el-table-column label="评分" width="90">
            <template #default="{ row }">{{ formatNumber(row.overall_score) }}</template>
          </el-table-column>
          <el-table-column label="变化" width="90">
            <template #default="{ row }">
              <span :class="scoreClass(row.score_change)">
                {{ row.score_change === null || row.score_change === undefined ? '-' : `${row.score_change > 0 ? '+' : ''}${row.score_change}` }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="opportunity_grade" label="等级" width="80" />
          <el-table-column prop="risk_level" label="风险" width="80" />
          <el-table-column prop="trend" label="趋势" />
          <el-table-column label="分析价" width="120">
            <template #default="{ row }">{{ formatPrice(row.analysis_price) }}</template>
          </el-table-column>
        </el-table>
      </section>

      <section class="section">
        <div class="section-header replay-header">
          <div>
            <h2>复盘模式</h2>
            <span>拉取分析时间点后的 K 线，检查关键价位是否触达</span>
          </div>
          <div class="replay-controls">
            <el-select v-model="replayBar" size="small">
              <el-option label="5m" value="5m" />
              <el-option label="15m" value="15m" />
              <el-option label="1H" value="1H" />
              <el-option label="4H" value="4H" />
              <el-option label="1D" value="1D" />
            </el-select>
            <el-button type="primary" size="small" :loading="replayLoading" @click="runReplay">
              开始复盘
            </el-button>
          </div>
        </div>

        <template v-if="replay">
          <div class="replay-summary">
            <span>K线 {{ replay.bar_count }} 根</span>
            <span>命中 {{ replay.summary.hit_levels }} / {{ replay.summary.total_levels }}</span>
          </div>
          <el-table :data="replay.levels" stripe size="small">
            <el-table-column prop="name" label="价位" width="120" />
            <el-table-column label="价格" width="120">
              <template #default="{ row }">{{ formatPrice(row.price) }}</template>
            </el-table-column>
            <el-table-column label="结果" width="100">
              <template #default="{ row }">
                <el-tag :type="row.hit ? 'success' : 'info'" size="small">
                  {{ row.hit ? '已触达' : '未触达' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="hit_time" label="首次触达时间" width="170" />
            <el-table-column label="触达收盘价" width="120">
              <template #default="{ row }">{{ formatPrice(row.hit_close) }}</template>
            </el-table-column>
          </el-table>

          <div class="candles-title">后续 K 线</div>
          <el-table :data="(replay.candles || []).slice(0, 40)" stripe size="small">
            <el-table-column prop="time" label="时间" width="170" />
            <el-table-column label="开" width="100"><template #default="{ row }">{{ formatPrice(row.open) }}</template></el-table-column>
            <el-table-column label="高" width="100"><template #default="{ row }">{{ formatPrice(row.high) }}</template></el-table-column>
            <el-table-column label="低" width="100"><template #default="{ row }">{{ formatPrice(row.low) }}</template></el-table-column>
            <el-table-column label="收" width="100"><template #default="{ row }">{{ formatPrice(row.close) }}</template></el-table-column>
          </el-table>
        </template>
      </section>
    </template>

    <ConfirmDialog
      v-model="deleteDialogVisible"
      title="删除历史分析记录"
      message="删除后无法恢复，确认要删除这条历史分析记录吗？"
      :description="record ? `${record.symbol} · ${record.created_at}` : ''"
      confirm-text="删除"
      danger
      :loading="deleting"
      @confirm="confirmDelete"
    />
  </div>
</template>

<style scoped>
.history-detail {
  max-width: 1440px;
  margin: 0 auto;
  padding: 24px 28px 64px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail-toolbar,
.toolbar-actions,
.replay-controls,
.replay-summary,
.note-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.detail-toolbar {
  margin-bottom: 2px;
}

.toolbar-title {
  flex: 1;
}

.toolbar-title h2,
.section-header h2 {
  margin: 0;
  color: var(--text-primary);
}

.eyebrow,
.section-header span {
  color: var(--text-muted);
  font-size: 12px;
}

.eyebrow {
  text-transform: uppercase;
}

.history-tools {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.8fr);
  gap: 18px;
}

.price-compare,
.note-box,
.section {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}

.price-compare {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  padding: 14px;
}

.metric {
  min-height: 78px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
}

.metric span {
  color: var(--text-muted);
  font-size: 12px;
}

.metric strong {
  color: var(--text-primary);
}

.note-box,
.section {
  padding: 18px;
}

.section-header {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}

.note-actions {
  justify-content: flex-end;
  margin-top: 10px;
}

.replay-header {
  align-items: center;
}

.replay-controls .el-select {
  width: 100px;
}

.replay-summary {
  margin-bottom: 12px;
  color: var(--text-muted);
}

.candles-title {
  margin: 18px 0 10px;
  color: var(--text-primary);
  font-weight: 600;
}

.positive {
  color: var(--accent-green) !important;
}

.negative {
  color: var(--accent-red) !important;
}

@media (max-width: 980px) {
  .history-tools,
  .price-compare {
    grid-template-columns: 1fr;
  }

  .detail-toolbar,
  .section-header,
  .replay-header {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 640px) {
  .history-detail {
    padding: 12px;
  }
}
</style>
