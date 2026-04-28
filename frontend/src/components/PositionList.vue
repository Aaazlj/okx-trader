<script setup lang="ts">
import type { Position } from '../stores/trading'

defineProps<{ positions: Position[] }>()
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
      <div style="display: flex; align-items: center; gap: 20px; font-size: 13px">
        <span style="color: var(--text-secondary)">
          {{ pos.quantity }} 张 · {{ pos.leverage }}x
        </span>
        <span style="color: var(--text-secondary)">
          入场 {{ pos.entry_price.toFixed(2) }}
        </span>
        <span
          class="pnl"
          :style="{ color: pos.unrealized_pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)' }"
        >
          {{ pos.unrealized_pnl >= 0 ? '+' : '' }}{{ pos.unrealized_pnl.toFixed(4) }} USDT
        </span>
      </div>
    </div>
  </div>
</template>
