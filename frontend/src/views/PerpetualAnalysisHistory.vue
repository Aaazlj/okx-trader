<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { deletePerpetualAnalysisHistory, getPerpetualAnalysisHistory } from '../api'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const router = useRouter()

const filters = reactive({
  symbol: '',
  start: '',
  end: '',
})
const records = ref<any[]>([])
const total = ref(0)
const loading = ref(false)
const deleting = ref(false)
const deleteDialogVisible = ref(false)
const pendingDeleteRecord = ref<any>(null)
const limit = 30
const offset = ref(0)
const deleteDescription = computed(() => {
  if (!pendingDeleteRecord.value) return ''
  return `${pendingDeleteRecord.value.symbol} · ${pendingDeleteRecord.value.created_at}`
})

onMounted(() => {
  loadRecords(true)
})

async function loadRecords(reset = false) {
  if (reset) offset.value = 0
  loading.value = true
  try {
    const params: any = {
      limit,
      offset: offset.value,
    }
    if (filters.symbol.trim()) params.symbol = filters.symbol.trim().toUpperCase()
    if (filters.start) params.start = filters.start
    if (filters.end) params.end = filters.end

    const { data } = await getPerpetualAnalysisHistory(params)
    records.value = data.items || []
    total.value = data.total || 0
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '历史记录加载失败')
  } finally {
    loading.value = false
  }
}

function openDetail(row: any) {
  router.push(`/analysis/history/${row.id}`)
}

function requestDelete(row: any) {
  pendingDeleteRecord.value = row
  deleteDialogVisible.value = true
}

async function confirmDelete() {
  if (!pendingDeleteRecord.value) return

  deleting.value = true
  try {
    await deletePerpetualAnalysisHistory(pendingDeleteRecord.value.id)
    ElMessage.success('历史记录已删除')
    deleteDialogVisible.value = false
    pendingDeleteRecord.value = null
    if (records.value.length === 1 && offset.value > 0) {
      offset.value = Math.max(0, offset.value - limit)
      await loadRecords()
    } else {
      await loadRecords()
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  } finally {
    deleting.value = false
  }
}

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  if (value >= 100) return value.toLocaleString('en-US', { maximumFractionDigits: 2 })
  if (value >= 1) return value.toLocaleString('en-US', { maximumFractionDigits: 4 })
  return value.toLocaleString('en-US', { maximumFractionDigits: 8 })
}

function formatScore(value: number | null | undefined) {
  return value === null || value === undefined ? '-' : value.toFixed(0)
}

function nextPage() {
  if (offset.value + limit >= total.value) return
  offset.value += limit
  loadRecords()
}

function prevPage() {
  offset.value = Math.max(0, offset.value - limit)
  loadRecords()
}
</script>

<template>
  <div class="history-page">
    <div class="history-toolbar">
      <div class="toolbar-title">
        <span class="eyebrow">Perpetual Analysis</span>
        <h2>历史分析记录</h2>
      </div>
      <el-button type="primary" @click="router.push('/analysis')">
        <el-icon><DataAnalysis /></el-icon>
        新分析
      </el-button>
    </div>

    <section class="filter-bar">
      <label>
        <span>交易对</span>
        <el-input
          v-model="filters.symbol"
          clearable
          placeholder="BTC-USDT-SWAP"
          @keyup.enter="loadRecords(true)"
        />
      </label>
      <label>
        <span>开始日期</span>
        <input v-model="filters.start" type="date" />
      </label>
      <label>
        <span>结束日期</span>
        <input v-model="filters.end" type="date" />
      </label>
      <div>
        <el-button type="primary" :loading="loading" @click="loadRecords(true)">筛选</el-button>
        <el-button @click="filters.symbol = ''; filters.start = ''; filters.end = ''; loadRecords(true)">重置</el-button>
      </div>
    </section>

    <section class="history-table">
      <el-table
        v-loading="loading"
        :data="records"
        stripe
        size="small"
        @row-click="openDetail"
      >
        <el-table-column prop="created_at" label="分析时间" width="170" />
        <el-table-column prop="symbol" label="交易对" width="150" />
        <el-table-column label="评分" width="90">
          <template #default="{ row }">{{ formatScore(row.overall_score) }}</template>
        </el-table-column>
        <el-table-column prop="opportunity_grade" label="等级" width="80" />
        <el-table-column prop="risk_level" label="风险" width="80" />
        <el-table-column prop="trend" label="趋势" width="120" />
        <el-table-column label="分析价" width="120">
          <template #default="{ row }">{{ formatPrice(row.analysis_price) }}</template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="112" align="center">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button
                class="action-btn action-btn--view"
                size="small"
                circle
                title="查看详情"
                @click.stop="openDetail(row)"
              >
                <el-icon><View /></el-icon>
              </el-button>
              <el-button
                class="action-btn action-btn--delete"
                size="small"
                circle
                title="删除记录"
                @click.stop="requestDelete(row)"
              >
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <span>共 {{ total }} 条</span>
        <div>
          <el-button size="small" :disabled="offset === 0" @click="prevPage">上一页</el-button>
          <el-button size="small" :disabled="offset + limit >= total" @click="nextPage">下一页</el-button>
        </div>
      </div>
    </section>

    <ConfirmDialog
      v-model="deleteDialogVisible"
      title="删除历史分析记录"
      message="删除后无法恢复，确认要删除这条历史分析记录吗？"
      :description="deleteDescription"
      confirm-text="删除"
      danger
      :loading="deleting"
      @confirm="confirmDelete"
    />
  </div>
</template>

<style scoped>
.history-page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.history-toolbar,
.filter-bar,
.pager {
  display: flex;
  align-items: center;
  gap: 12px;
}

.history-toolbar {
  justify-content: space-between;
  margin-bottom: 18px;
}

.toolbar-title h2 {
  margin: 2px 0 0;
  color: var(--text-primary);
}

.eyebrow {
  color: var(--text-muted);
  font-size: 12px;
  text-transform: uppercase;
}

.filter-bar {
  flex-wrap: wrap;
  align-items: flex-end;
  padding: 16px;
  margin-bottom: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
}

.filter-bar label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--text-muted);
  font-size: 12px;
}

.filter-bar .el-input {
  width: 210px;
}

.filter-bar input[type="date"] {
  height: 32px;
  padding: 0 10px;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.history-table {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px;
}

.row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 2px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--bg-primary);
}

.row-actions .el-button + .el-button {
  margin-left: 0;
}

.action-btn {
  width: 28px;
  height: 28px;
  border: none !important;
  background: transparent !important;
  color: var(--text-muted) !important;
}

.action-btn--view:hover {
  background: var(--accent-amber-glow) !important;
  color: var(--accent-amber-dark) !important;
}

.action-btn--delete:hover {
  background: var(--accent-red-bg) !important;
  color: var(--accent-red) !important;
}

.pager {
  justify-content: space-between;
  padding: 14px 4px 2px;
  color: var(--text-muted);
  font-size: 12px;
}

@media (max-width: 720px) {
  .history-page {
    padding: 16px;
  }

  .history-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .filter-bar {
    align-items: stretch;
  }
}
</style>
