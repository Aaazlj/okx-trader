<script setup lang="ts">
import type { Position } from '../stores/trading'

defineProps<{ positions: Position[] }>()

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
</script>

<template>
  <div v-if="positions.length === 0" class="empty-state">
    <div class="icon">📭</div>
    <div>暂无持仓</div>
  </div>
  <div v-else class="position-list">
    <div v-for="pos in positions" :key="pos.symbol" class="position-item">
      <div style="display: flex; align-items: center; gap: 12px">
        <span class="symbol">{{ pos.symbol.replace('-USDT-SWAP', '') }}</span>
        <span class="direction" :class="pos.direction">{{ pos.direction }}</span>
      </div>
      <div style="display: flex; align-items: center; gap: 16px; font-size: 12px; flex-wrap: wrap">
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
      </div>
    </div>
  </div>
</template>
