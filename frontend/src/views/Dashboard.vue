<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { closePosition } from '../api'
import { useTradingStore, type Position } from '../stores/trading'
import StrategyCard from '../components/StrategyCard.vue'
import PositionList from '../components/PositionList.vue'
import LogViewer from '../components/LogViewer.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const store = useTradingStore()
const closeDialogVisible = ref(false)
const pendingClosePosition = ref<Position | null>(null)
const closingKey = ref('')

const closeDescription = computed(() => {
  const pos = pendingClosePosition.value
  if (!pos) return ''
  const pnl = `${pos.unrealized_pnl >= 0 ? '+' : ''}${pos.unrealized_pnl.toFixed(4)} USDT`
  return `${pos.symbol} · ${pos.direction} · ${pos.quantity} 张 · 未实现盈亏 ${pnl}`
})

function positionKey(pos: Position): string {
  return `${pos.symbol}:${pos.pos_side || pos.direction}`
}

function closeRequestSide(pos: Position): string {
  return pos.pos_side && pos.pos_side !== 'net' ? pos.pos_side : pos.direction
}

function requestClosePosition(pos: Position) {
  pendingClosePosition.value = pos
  closeDialogVisible.value = true
}

async function confirmClosePosition() {
  if (!pendingClosePosition.value) return

  const pos = pendingClosePosition.value
  closingKey.value = positionKey(pos)
  try {
    await closePosition(pos.symbol, closeRequestSide(pos))
    ElMessage.success(`${pos.symbol} 已提交市价平仓`)
    closeDialogVisible.value = false
    pendingClosePosition.value = null
    await Promise.allSettled([
      store.fetchPositions(),
      store.fetchAccount(),
      store.fetchTrades(),
      store.fetchStrategiesStats(),
    ])
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '平仓失败')
  } finally {
    closingKey.value = ''
  }
}
</script>

<template>
  <div class="dashboard">
    <!-- 账户统计 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="label">总权益</div>
        <div class="value">{{ store.account.total_equity.toFixed(2) }} USDT</div>
      </div>
      <div class="stat-card">
        <div class="label">可用余额</div>
        <div class="value">{{ store.account.available_balance.toFixed(2) }} USDT</div>
      </div>
      <div class="stat-card">
        <div class="label">未实现盈亏</div>
        <div
          class="value"
          :class="store.account.unrealized_pnl >= 0 ? 'positive' : 'negative'"
        >
          {{ store.account.unrealized_pnl >= 0 ? '+' : '' }}{{ store.account.unrealized_pnl.toFixed(2) }} USDT
        </div>
      </div>
      <div class="stat-card">
        <div class="label">运行中策略</div>
        <div class="value">
          {{ store.strategies.filter((s) => s.is_active).length }} / {{ store.strategies.length }}
        </div>
      </div>
      <div class="stat-card">
        <div class="label">当前持仓</div>
        <div class="value">{{ store.positions.length }}</div>
      </div>
    </div>

    <!-- 策略面板 -->
    <div class="section">
      <div class="section-header">
        <h2>⚙️ 策略管理</h2>
        <el-button size="small" @click="store.fetchStrategies()">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
      <div class="section-body">
        <div class="strategy-grid">
          <StrategyCard
            v-for="strategy in store.strategies"
            :key="strategy.id"
            :strategy="strategy"
          />
        </div>
      </div>
    </div>

    <!-- 持仓列表 -->
    <div class="section">
      <div class="section-header">
        <h2>📊 当前持仓</h2>
      </div>
      <div class="section-body">
        <PositionList
          :positions="store.positions"
          :closing-key="closingKey"
          @close="requestClosePosition"
        />
      </div>
    </div>

    <!-- 实时日志 -->
    <div class="section">
      <div class="section-header">
        <h2>📋 实时日志</h2>
        <span style="font-size: 12px; color: var(--text-muted)">
          {{ store.logs.length }} 条记录
        </span>
      </div>
      <div class="section-body">
        <LogViewer :logs="store.logs" />
      </div>
    </div>

    <ConfirmDialog
      v-model="closeDialogVisible"
      title="手动平仓"
      message="会向 OKX 提交市价全平该持仓，确认继续？"
      :description="closeDescription"
      confirm-text="平仓"
      danger
      :loading="Boolean(closingKey)"
      @confirm="confirmClosePosition"
    />
  </div>
</template>
