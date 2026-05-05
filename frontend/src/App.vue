<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { getAuthStatus, login, setUnauthorizedHandler } from './api'
import { useTradingStore } from './stores/trading'

const logoUrl = new URL('./assets/logo.svg', import.meta.url).href

const store = useTradingStore()
const route = useRoute()
const router = useRouter()

const isDetailPage = computed(() => route.name === 'strategy-detail')
const isSettingsPage = computed(() => route.name === 'settings')
const isAnalysisArea = computed(() => String(route.name || '').startsWith('perpetual-analysis'))
const authLoaded = ref(false)
const authEnabled = ref(false)
const authenticated = ref(false)
const password = ref('')
const loginLoading = ref(false)
const loginError = ref('')
const showLogin = computed(() => authLoaded.value && authEnabled.value && !authenticated.value)
const showPanel = computed(() => authLoaded.value && (!authEnabled.value || authenticated.value))

let refreshTimer: number | undefined
let panelStarted = false

onMounted(async () => {
  setUnauthorizedHandler(handleUnauthorized)
  await loadAuthStatus()
  if (showPanel.value) {
    startPanel()
  }
})

onUnmounted(() => {
  setUnauthorizedHandler(null)
  stopPanel()
})

async function loadAuthStatus() {
  try {
    const { data } = await getAuthStatus()
    authEnabled.value = data.enabled
    authenticated.value = data.authenticated
  } catch {
    authEnabled.value = true
    authenticated.value = false
    loginError.value = '无法加载登录状态，请稍后重试'
  } finally {
    authLoaded.value = true
  }
}

function startPanel() {
  if (panelStarted) return
  panelStarted = true
  store.fetchAll()
  store.connectWS()
  refreshTimer = window.setInterval(() => store.fetchAll(), 30000)
}

function stopPanel() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = undefined
  }
  panelStarted = false
  store.disconnectWS()
}

function handleUnauthorized() {
  if (!authEnabled.value) return
  authenticated.value = false
  authLoaded.value = true
  loginError.value = '登录已过期，请重新登录'
  stopPanel()
}

async function submitLogin() {
  loginError.value = ''
  loginLoading.value = true
  try {
    await login(password.value)
    password.value = ''
    const { data } = await getAuthStatus()
    authEnabled.value = data.enabled
    authenticated.value = data.authenticated
    if (authenticated.value) {
      startPanel()
    } else {
      loginError.value = '登录失败，请重试'
    }
  } catch {
    loginError.value = '密码错误'
    ElMessage.error('密码错误')
  } finally {
    loginLoading.value = false
  }
}

function goBack() {
  router.push('/')
}
</script>

<template>
  <el-config-provider :locale="zhCn">
  <div id="app">
    <div v-if="!authLoaded" class="auth-shell">
      <div class="auth-card auth-loading">
        <img class="auth-logo" :src="logoUrl" alt="OKX Trader" />
        <p>正在加载面板...</p>
      </div>
    </div>

    <div v-else-if="showLogin" class="auth-shell">
      <form class="auth-card" @submit.prevent="submitLogin">
        <img class="auth-logo" :src="logoUrl" alt="OKX Trader" />
        <h1>面板登录</h1>
        <p class="auth-subtitle">输入管理员密码后进入 OKX 自动交易系统</p>
        <el-input
          v-model="password"
          type="password"
          size="large"
          placeholder="ADMIN_PASSWORD"
          show-password
          autofocus
        />
        <p v-if="loginError" class="auth-error">{{ loginError }}</p>
        <el-button
          native-type="submit"
          type="primary"
          size="large"
          :loading="loginLoading"
          :disabled="!password"
        >
          登录
        </el-button>
      </form>
    </div>

    <template v-else>
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
          <div>
            <el-button
              size="small"
              circle
              :type="isAnalysisArea ? 'primary' : 'default'"
              @click="router.push('/analysis')"
              title="永续合约分析"
            >
              <el-icon><DataAnalysis /></el-icon>
            </el-button>
            <el-button
              size="small"
              circle
              :type="route.name === 'perpetual-analysis-history' ? 'primary' : 'default'"
              @click="router.push('/analysis/history')"
              title="分析历史"
            >
              <el-icon><Clock /></el-icon>
            </el-button>
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
        </div>
      </header>
      <router-view />
    </template>
  </div>
  </el-config-provider>
</template>

<style scoped>
.auth-shell {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    radial-gradient(circle at top, rgba(196, 144, 96, 0.16), transparent 34%),
    var(--bg-primary);
}

.auth-card {
  width: min(420px, 100%);
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 34px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
}

.auth-loading {
  align-items: center;
  color: var(--text-secondary);
}

.auth-logo {
  width: 52px;
  height: 52px;
  align-self: center;
}

.auth-card h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 28px;
  color: var(--text-primary);
  text-align: center;
}

.auth-subtitle {
  margin: -8px 0 4px;
  color: var(--text-secondary);
  text-align: center;
  font-size: 14px;
}

.auth-error {
  margin: -6px 0 0;
  color: var(--accent-red);
  font-size: 13px;
}
</style>
