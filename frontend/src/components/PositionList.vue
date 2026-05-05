<script setup lang="ts">
import type { Position } from '../stores/trading'

defineProps<{
  positions: Position[]
  closingKey?: string
}>()

const emit = defineEmits<{
  (e: 'close', position: Position): void
}>()

function formatDuration(seconds: number): string {
  if (seconds <= 0) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h${m}m`
  return `${m}m`
}

function distLabel(pct: number | null, target: 'tp' | 'sl'): string {
  if (pct === null || pct === undefined) return '-'
  const arrow = target === 'tp' ? '↑' : '↓'
  return `${arrow}${Math.abs(pct).toFixed(1)}%`
}

function positionKey(pos: Position): string {
  return `${pos.symbol}:${pos.pos_side || pos.direction}`
}
</script>

<template>
  <div v-if="positions.length === 0" class="empty-state">
    <div class="icon">📭</div>
    <div>暂无持仓</div>
  </div>
  <div v-else class="position-list">
    <div v-for="pos in positions" :key="positionKey(pos)" class="position-item">
      <div class="position-main">
        <span class="symbol">{{ pos.symbol.replace('-USDT-SWAP', '') }}</span>
        <span class="direction" :class="pos.direction">{{ pos.direction }}</span>
      </div>
      <div class="position-detail">
        <span style="color: var(--text-secondary)">
          {{ pos.quantity }} 张 · {{ pos.leverage }}x
        </span>
        <span style="color: var(--text-secondary)">
          入场 {{ pos.entry_price.toFixed(2) }}
        </span>
        <span style="color: var(--text-secondary)">
          现价 {{ (pos.current_price || 0).toFixed(2) }}
        </span>
        <span
          class="pnl"
          :style="{ color: pos.unrealized_pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)' }"
        >
          {{ pos.unrealized_pnl >= 0 ? '+' : '' }}{{ pos.unrealized_pnl.toFixed(4) }} USDT
        </span>
        <span v-if="pos.tp_distance_pct !== null" style="color: var(--accent-green)">
          TP {{ distLabel(pos.tp_distance_pct, 'tp') }}
        </span>
        <span v-if="pos.sl_distance_pct !== null" style="color: var(--accent-red)">
          SL {{ distLabel(pos.sl_distance_pct, 'sl') }}
        </span>
        <span style="color: var(--text-muted)">
          {{ formatDuration(pos.holding_seconds) }}
        </span>
        <el-button
          class="position-close-btn"
          type="danger"
          size="small"
          :loading="closingKey === positionKey(pos)"
          @click="emit('close', pos)"
        >
          <el-icon><Delete /></el-icon>
          平仓
        </el-button>
      </div>
    </div>
  </div>
</template>
