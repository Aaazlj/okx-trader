<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTradingStore } from './stores/trading'

const logoUrl = new URL('./assets/logo.svg', import.meta.url).href

const store = useTradingStore()
const route = useRoute()
const router = useRouter()

const isDetailPage = computed(() => route.name === 'strategy-detail')
const isSettingsPage = computed(() => route.name === 'settings')

onMounted(() => {
  store.fetchAll()
  store.connectWS()
  // 定时刷新（30秒）
  const timer = setInterval(() => store.fetchAll(), 30000)
  onUnmounted(() => {
    clearInterval(timer)
    store.disconnectWS()
  })
})

function goBack() {
  router.push('/')
}
</script>

<template>
  <div id="app">
    <header class="app-header">
      <div class="logo" style="display: flex; align-items: center; gap: 12px">
        <el-button
          v-if="isDetailPage"
          size="small"
          circle
          @click="goBack"
          style="margin-right: 4px"
        >
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <img class="app-logo" :src="logoUrl" alt="OKX Trader" @click="goBack" />
        <h1 @click="goBack" style="cursor: pointer">OKX 自动交易系统</h1>
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
        <el-button
          size="small"
          circle
          :type="isSettingsPage ? 'primary' : 'default'"
          @click="router.push('/settings')"
          title="系统设置"
        >
          <el-icon><Setting /></el-icon>
        </el-button>
      </div>
    </header>
    <router-view />
  </div>
</template>
