<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { startStrategy, stopStrategy, updateStrategy, getSymbols } from '../api'
import { useTradingStore, type Strategy } from '../stores/trading'

const props = defineProps<{ strategy: Strategy }>()
const store = useTradingStore()

const toggling = ref(false)
const showConfig = ref(false)

// 编辑表单
const editForm = ref({
  symbols: [] as string[],
  decision_mode: 'technical' as 'technical' | 'ai',
  leverage: 10,
  order_amount_usdt: 50,
  ai_min_confidence: 70,
  ai_prompt: '',
})

async function toggleActive() {
  toggling.value = true
  try {
    if (props.strategy.is_active) {
      await stopStrategy(props.strategy.id)
      ElMessage.warning(`策略 ${props.strategy.name} 已暂停`)
    } else {
      await startStrategy(props.strategy.id)
      ElMessage.success(`策略 ${props.strategy.name} 已启动`)
    }
    await store.fetchStrategies()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
  toggling.value = false
}

function openConfig() {
  editForm.value = {
    symbols: [...props.strategy.symbols],
    decision_mode: props.strategy.decision_mode,
    leverage: props.strategy.leverage,
    order_amount_usdt: props.strategy.order_amount_usdt,
    ai_min_confidence: props.strategy.ai_min_confidence,
    ai_prompt: props.strategy.ai_prompt,
  }
  showConfig.value = true
}

async function saveConfig() {
  try {
    await updateStrategy(props.strategy.id, editForm.value)
    ElMessage.success('配置已保存')
    showConfig.value = false
    await store.fetchStrategies()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  }
}

// 可用交易对选项
const symbolOptions = ref<string[]>([])
async function loadSymbols() {
  if (symbolOptions.value.length > 0) return
  try {
    const { data } = await getSymbols()
    symbolOptions.value = data.map((s: any) => s.inst_id)
  } catch {
    symbolOptions.value = [
      'ETH-USDT-SWAP', 'BTC-USDT-SWAP', 'SOL-USDT-SWAP',
      'DOGE-USDT-SWAP', 'XRP-USDT-SWAP',
    ]
  }
}
</script>

<template>
  <div class="strategy-card" :class="{ active: strategy.is_active }">
    <div class="card-top">
      <div>
        <span class="status-dot" :class="strategy.is_active ? 'running' : 'stopped'" />
        <span class="strategy-name">{{ strategy.name }}</span>
      </div>
      <div style="display: flex; gap: 6px">
        <el-button
          size="small"
          :type="strategy.is_active ? 'danger' : 'success'"
          :loading="toggling"
          @click="toggleActive"
        >
          {{ strategy.is_active ? '暂停' : '启动' }}
        </el-button>
        <el-button size="small" @click="openConfig">
          <el-icon><Setting /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- 决策模式 -->
    <div class="config-row">
      <span class="config-label">决策模式</span>
      <div class="mode-switch">
        <span class="mode-btn" :class="{ active: strategy.decision_mode === 'technical' }">
          📐 技术指标
        </span>
        <span class="mode-btn" :class="{ active: strategy.decision_mode === 'ai' }">
          🤖 AI驱动
        </span>
      </div>
    </div>

    <!-- 交易对 -->
    <div class="config-row">
      <span class="config-label">交易对</span>
      <div class="symbols-tags">
        <span v-for="sym in strategy.symbols" :key="sym" class="symbol-tag">
          {{ sym.replace('-USDT-SWAP', '') }}
        </span>
      </div>
    </div>

    <!-- 参数 -->
    <div class="config-row">
      <span class="config-label">参数</span>
      <span style="font-size: 12px; color: var(--text-secondary)">
        {{ strategy.leverage }}x · {{ strategy.order_amount_usdt }} USDT · {{ strategy.mgn_mode }}
      </span>
    </div>

    <!-- 配置对话框 -->
    <el-dialog
      v-model="showConfig"
      :title="`配置 — ${strategy.name}`"
      width="520px"
      @open="loadSymbols"
    >
      <el-form label-width="100px" size="default">
        <el-form-item label="交易对">
          <el-select v-model="editForm.symbols" multiple filterable placeholder="选择交易对">
            <el-option
              v-for="sym in symbolOptions"
              :key="sym"
              :label="sym"
              :value="sym"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="决策模式">
          <el-radio-group v-model="editForm.decision_mode">
            <el-radio value="technical">📐 纯技术指标</el-radio>
            <el-radio value="ai">🤖 AI 驱动</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="杠杆倍数">
          <el-input-number v-model="editForm.leverage" :min="1" :max="100" :step="1" />
        </el-form-item>

        <el-form-item label="每单金额">
          <el-input-number v-model="editForm.order_amount_usdt" :min="5" :step="10" />
          <span style="margin-left: 8px; color: var(--text-secondary)">USDT</span>
        </el-form-item>

        <template v-if="editForm.decision_mode === 'ai'">
          <el-divider content-position="left">AI 配置</el-divider>

          <el-form-item label="最低置信度">
            <el-slider v-model="editForm.ai_min_confidence" :min="0" :max="100" :step="5" show-input />
          </el-form-item>

          <el-form-item label="自定义 Prompt">
            <el-input
              v-model="editForm.ai_prompt"
              type="textarea"
              :rows="4"
              placeholder="额外分析要求（可选）"
            />
          </el-form-item>
        </template>
      </el-form>

      <template #footer>
        <el-button @click="showConfig = false">取消</el-button>
        <el-button type="primary" @click="saveConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
