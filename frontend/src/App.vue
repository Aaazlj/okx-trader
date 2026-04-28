<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useTradingStore } from './stores/trading'
import Dashboard from './views/Dashboard.vue'

const store = useTradingStore()

onMounted(() => {
  document.documentElement.classList.add('dark')
  store.fetchAll()
  store.connectWS()
  // 定时刷新（30秒）
  const timer = setInterval(() => store.fetchAll(), 30000)
  onUnmounted(() => {
    clearInterval(timer)
    store.disconnectWS()
  })
})
</script>

<template>
  <div id="app">
    <header class="app-header">
      <div class="logo">
        <h1>⚡ OKX 自动交易系统</h1>
      </div>
      <div style="display: flex; align-items: center; gap: 12px">
        <span
          class="mode-badge"
          :class="store.account.mode === '模拟盘' ? 'demo' : 'live'"
        >
          {{ store.account.mode }}
        </span>
        <span
          style="font-size: 11px"
          :style="{ color: store.wsConnected ? 'var(--accent-green)' : 'var(--text-muted)' }"
        >
          ● {{ store.wsConnected ? '已连接' : '未连接' }}
        </span>
      </div>
    </header>
    <Dashboard />
  </div>
</template>
