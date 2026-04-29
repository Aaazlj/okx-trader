<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getSettings,
  updateSettings,
  testAI,
  testOKX,
  testTelegram,
} from '../api'

interface Settings {
  okx_api_key: string
  okx_secret_key: string
  okx_passphrase: string
  okx_demo: boolean
  http_proxy: string
  https_proxy: string
  openai_api_key: string
  openai_api_url: string
  openai_model: string
  telegram_bot_token: string
  telegram_chat_id: string
}

const form = ref<Settings>({
  okx_api_key: '',
  okx_secret_key: '',
  okx_passphrase: '',
  okx_demo: true,
  http_proxy: '',
  https_proxy: '',
  openai_api_key: '',
  openai_api_url: 'https://api.openai.com/v1',
  openai_model: 'gpt-4o-mini',
  telegram_bot_token: '',
  telegram_chat_id: '',
})

const loading = ref(false)
const saving = ref(false)
const testingAI = ref(false)
const testingOKX = ref(false)
const testingTG = ref(false)

const showOKXSecret = ref(false)
const showAISecret = ref(false)
const showTGSecret = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const { data } = await getSettings()
    form.value = data
  } catch (e: any) {
    ElMessage.error('加载配置失败: ' + (e.message || e))
  } finally {
    loading.value = false
  }
})

async function handleSave() {
  saving.value = true
  try {
    const { data } = await updateSettings(form.value)
    ElMessage.success(data.message || '保存成功')
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function handleTestAI() {
  testingAI.value = true
  try {
    const { data } = await testAI(form.value)
    if (data.success) {
      ElMessage.success(data.message)
    } else {
      ElMessage.warning(data.message)
    }
  } catch (e: any) {
    ElMessage.error('测试失败: ' + (e.message || e))
  } finally {
    testingAI.value = false
  }
}

async function handleTestOKX() {
  testingOKX.value = true
  try {
    const { data } = await testOKX(form.value)
    if (data.success) {
      ElMessage.success(data.message)
    } else {
      ElMessage.warning(data.message)
    }
  } catch (e: any) {
    ElMessage.error('测试失败: ' + (e.message || e))
  } finally {
    testingOKX.value = false
  }
}

async function handleTestTG() {
  testingTG.value = true
  try {
    const { data } = await testTelegram(form.value)
    if (data.success) {
      ElMessage.success(data.message)
    } else {
      ElMessage.warning(data.message)
    }
  } catch (e: any) {
    ElMessage.error('测试失败: ' + (e.message || e))
  } finally {
    testingTG.value = false
  }
}
</script>

<template>
  <div class="settings-page" v-loading="loading">
    <!-- OKX 交易所配置 -->
    <div class="section">
      <div class="section-header">
        <h2>
          <span style="font-size: 18px">🏦</span>
          OKX 交易所
        </h2>
        <el-button
          size="small"
          type="primary"
          :loading="testingOKX"
          @click="handleTestOKX"
        >
          测试连接
        </el-button>
      </div>
      <div class="section-body">
        <div class="form-grid">
          <div class="form-item">
            <label>API Key</label>
            <el-input
              v-model="form.okx_api_key"
              placeholder="OKX API Key"
              clearable
            />
          </div>
          <div class="form-item">
            <label>Secret Key</label>
            <el-input
              v-model="form.okx_secret_key"
              :type="showOKXSecret ? 'text' : 'password'"
              placeholder="OKX Secret Key"
            >
              <template #suffix>
                <el-icon
                  class="eye-icon"
                  @click="showOKXSecret = !showOKXSecret"
                  style="cursor: pointer"
                >
                  <component :is="showOKXSecret ? 'View' : 'Hide'" />
                </el-icon>
              </template>
            </el-input>
          </div>
          <div class="form-item">
            <label>Passphrase</label>
            <el-input
              v-model="form.okx_passphrase"
              :type="showOKXSecret ? 'text' : 'password'"
              placeholder="OKX Passphrase"
            />
          </div>
          <div class="form-item">
            <label>交易模式</label>
            <div class="switch-row">
              <el-switch
                v-model="form.okx_demo"
                active-text="模拟盘"
                inactive-text="实盘"
                active-color="var(--accent-orange)"
                inactive-color="var(--accent-red)"
              />
              <el-tag
                :type="form.okx_demo ? 'warning' : 'danger'"
                size="small"
                effect="dark"
              >
                {{ form.okx_demo ? 'DEMO' : 'LIVE' }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- AI 服务配置 -->
    <div class="section">
      <div class="section-header">
        <h2>
          <span style="font-size: 18px">🤖</span>
          AI 服务
        </h2>
        <el-button
          size="small"
          type="primary"
          :loading="testingAI"
          @click="handleTestAI"
        >
          测试连通性
        </el-button>
      </div>
      <div class="section-body">
        <div class="form-grid">
          <div class="form-item full">
            <label>API URL</label>
            <el-input
              v-model="form.openai_api_url"
              placeholder="https://api.openai.com/v1"
              clearable
            />
          </div>
          <div class="form-item">
            <label>API Key</label>
            <el-input
              v-model="form.openai_api_key"
              :type="showAISecret ? 'text' : 'password'"
              placeholder="sk-..."
            >
              <template #suffix>
                <el-icon
                  class="eye-icon"
                  @click="showAISecret = !showAISecret"
                  style="cursor: pointer"
                >
                  <component :is="showAISecret ? 'View' : 'Hide'" />
                </el-icon>
              </template>
            </el-input>
          </div>
          <div class="form-item">
            <label>模型</label>
            <el-input
              v-model="form.openai_model"
              placeholder="gpt-4o-mini"
              clearable
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Telegram 配置 -->
    <div class="section">
      <div class="section-header">
        <h2>
          <span style="font-size: 18px">📨</span>
          Telegram 通知
        </h2>
        <el-button
          size="small"
          type="primary"
          :loading="testingTG"
          @click="handleTestTG"
        >
          发送测试消息
        </el-button>
      </div>
      <div class="section-body">
        <div class="form-grid">
          <div class="form-item">
            <label>Bot Token</label>
            <el-input
              v-model="form.telegram_bot_token"
              :type="showTGSecret ? 'text' : 'password'"
              placeholder="123456:ABC-DEF..."
            >
              <template #suffix>
                <el-icon
                  class="eye-icon"
                  @click="showTGSecret = !showTGSecret"
                  style="cursor: pointer"
                >
                  <component :is="showTGSecret ? 'View' : 'Hide'" />
                </el-icon>
              </template>
            </el-input>
          </div>
          <div class="form-item">
            <label>Chat ID</label>
            <el-input
              v-model="form.telegram_chat_id"
              placeholder="-1001234567890"
              clearable
            />
          </div>
        </div>
      </div>
    </div>

    <!-- 代理配置 -->
    <div class="section">
      <div class="section-header">
        <h2>
          <span style="font-size: 18px">🌐</span>
          网络代理
        </h2>
      </div>
      <div class="section-body">
        <div class="form-grid">
          <div class="form-item">
            <label>HTTP Proxy</label>
            <el-input
              v-model="form.http_proxy"
              placeholder="http://127.0.0.1:7890"
              clearable
            />
          </div>
          <div class="form-item">
            <label>HTTPS Proxy</label>
            <el-input
              v-model="form.https_proxy"
              placeholder="http://127.0.0.1:7890"
              clearable
            />
          </div>
        </div>
      </div>
    </div>

    <!-- 保存按钮 -->
    <div class="save-bar">
      <el-button
        type="primary"
        size="large"
        :loading="saving"
        @click="handleSave"
      >
        保存配置
      </el-button>
      <span class="save-hint">保存后立即生效</span>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  max-width: 800px;
  margin: 0 auto;
  padding: 20px 24px 80px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-item.full {
  grid-column: 1 / -1;
}

.form-item label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.switch-row {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 32px;
}

.save-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-color);
  padding: 14px 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  z-index: 100;
  backdrop-filter: blur(12px);
}

.save-hint {
  font-size: 12px;
  color: var(--text-muted);
}

@media (max-width: 640px) {
  .form-grid {
    grid-template-columns: 1fr;
  }

  .settings-page {
    padding: 12px 12px 80px;
  }
}
</style>
