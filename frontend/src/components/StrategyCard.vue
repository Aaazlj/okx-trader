<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { startStrategy, stopStrategy, updateStrategy, getSymbols, generateMartingaleParams } from '../api'
import { useTradingStore, type Strategy } from '../stores/trading'

const props = defineProps<{ strategy: Strategy }>()
const store = useTradingStore()
const router = useRouter()

const stats = computed(() => store.strategyStats[props.strategy.id])
const isMartingale = computed(() => props.strategy.strategy_type === 'martingale_contract')

const toggling = ref(false)
const showConfig = ref(false)
const generatingParams = ref(false)
const martingaleRiskProfile = ref('balanced')

function defaultMartingaleParams() {
  return {
    cycle: 'medium',
    bar: '4H',
    direction: 'long',
    add_trigger_type: 'pct',
    add_trigger_value: 1.2,
    take_profit_type: 'pct',
    take_profit_value: 0.6,
    max_position_usdt: 300,
    initial_margin_usdt: 20,
    add_margin_usdt: 20,
    max_add_count: 5,
    hard_stop_pct: 8,
    fee_rate: 0.0005,
    slippage_pct: 0.02,
    risk: {
      max_concurrent: 1,
      max_daily_per_symbol: 3,
      max_daily_loss_pct: 3,
    },
  }
}

function cycleLabel(cycle: string) {
  if (cycle === 'short') return '短期'
  if (cycle === 'long') return '长期'
  return '中期'
}

function valueTypeLabel(type: string) {
  return type === 'usdt' ? 'U' : '%'
}

function cycleHelp(cycle: string) {
  if (cycle === 'short') return '短期使用 1H K线，适合更频繁的加仓与止盈判断'
  if (cycle === 'long') return '长期使用 1D K线，适合低频持仓'
  return '中期使用 4H K线，默认周期'
}

function addTriggerHelp() {
  const type = editForm.value.params.add_trigger_type
  const unit = type === 'usdt' ? 'U 表示 USDT 价格差' : '% 表示相对持仓均价的百分比'
  return `做多按下跌触发，做空按上涨触发；${unit}`
}

function takeProfitHelp() {
  const type = editForm.value.params.take_profit_type
  const unit = type === 'usdt' ? 'U 表示本轮持仓浮盈金额' : '% 表示相对持仓均价的收益比例'
  return `达到目标后整轮平仓；${unit}`
}

function maxPositionHelp() {
  return '自动计算：初次保证金 + 加仓保证金 × 最大自动加仓次数'
}

const plannedPositionUsdt = computed(() => {
  const p = editForm.value.params || {}
  return Number(p.initial_margin_usdt || 0) + Number(p.add_margin_usdt || 0) * Number(p.max_add_count || 0)
})

const selectedMaxLeverage = computed(() => {
  const selected = editForm.value.symbols || []
  const limits = selected
    .map((symbol) => symbolMaxLeverage.value[symbol])
    .filter((value) => Number.isFinite(value) && value > 0)
  return limits.length ? Math.min(...limits) : 100
})

const liquidationDistanceText = computed(() => {
  const leverage = Math.max(1, Number(editForm.value.leverage || 1))
  const distance = Math.max(0, 100 / leverage - 0.5)
  return `按当前 ${leverage}x 粗略估算，强平距离约 ${distance.toFixed(2)}%，具体强平价以 OKX 持仓返回为准`
})

function syncMartingaleBudget() {
  if (!isMartingale.value) return
  editForm.value.params.max_position_usdt = Number(plannedPositionUsdt.value.toFixed(4))
  editForm.value.order_amount_usdt = Number(editForm.value.params.initial_margin_usdt || 0)
}

function goToDetail() {
  router.push(`/strategy/${props.strategy.id}`)
}

// 编辑表单
const editForm = ref({
  symbols: [] as string[],
  decision_mode: 'technical' as 'technical' | 'ai' | 'hybrid',
  leverage: 10,
  order_amount_usdt: 50,
  ai_min_confidence: 70,
  ai_prompt: '',
  params: {} as Record<string, any>,
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
    decision_mode: isMartingale.value ? 'technical' : props.strategy.decision_mode,
    leverage: props.strategy.leverage,
    order_amount_usdt: props.strategy.order_amount_usdt,
    ai_min_confidence: props.strategy.ai_min_confidence,
    ai_prompt: props.strategy.ai_prompt,
    params: isMartingale.value
      ? { ...defaultMartingaleParams(), ...props.strategy.params, risk: { ...defaultMartingaleParams().risk, ...(props.strategy.params?.risk || {}) } }
      : { ...props.strategy.params },
  }
  showConfig.value = true
}

async function saveConfig() {
  try {
    if (isMartingale.value) {
      syncMartingaleBudget()
      if (editForm.value.leverage > selectedMaxLeverage.value) {
        ElMessage.error(`当前交易对最大支持 ${selectedMaxLeverage.value}x 杠杆`)
        return
      }
    }
    const payload = {
      ...editForm.value,
      decision_mode: isMartingale.value ? 'technical' : editForm.value.decision_mode,
      params: editForm.value.params,
    }
    if (isMartingale.value) {
      payload.order_amount_usdt = Number(editForm.value.params.initial_margin_usdt || editForm.value.order_amount_usdt)
    }
    await updateStrategy(props.strategy.id, payload)
    ElMessage.success('配置已保存')
    showConfig.value = false
    await store.fetchStrategies()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  }
}

async function generateParamsByAI() {
  const symbol = editForm.value.symbols[0] || props.strategy.symbols[0]
  if (!symbol) {
    ElMessage.warning('请先选择交易对')
    return
  }
  generatingParams.value = true
  try {
    const { data } = await generateMartingaleParams({
      symbol,
      cycle: editForm.value.params.cycle || 'medium',
      risk_profile: martingaleRiskProfile.value,
      max_position_usdt: plannedPositionUsdt.value || 300,
    })
    editForm.value.params = data.params
    syncMartingaleBudget()
    ElMessage.success('AI 参数已生成，请确认后保存')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || 'AI 参数生成失败')
  } finally {
    generatingParams.value = false
  }
}

// 可用交易对选项
const symbolOptions = ref<string[]>([])
const symbolMaxLeverage = ref<Record<string, number>>({})
async function loadSymbols() {
  if (symbolOptions.value.length > 0) return
  try {
    const { data } = await getSymbols()
    symbolOptions.value = data.map((s: any) => s.inst_id)
    symbolMaxLeverage.value = Object.fromEntries(
      data.map((s: any) => [s.inst_id, Number(s.max_leverage || 100)]),
    )
  } catch {
    symbolOptions.value = [
      'ETH-USDT-SWAP', 'BTC-USDT-SWAP', 'SOL-USDT-SWAP',
      'DOGE-USDT-SWAP', 'XRP-USDT-SWAP',
    ]
    symbolMaxLeverage.value = Object.fromEntries(symbolOptions.value.map((sym) => [sym, 100]))
  }
}
</script>

<template>
  <div class="strategy-card" :class="{ active: strategy.is_active }" @click="goToDetail" style="cursor: pointer">
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
          @click.stop="toggleActive"
        >
          {{ strategy.is_active ? '暂停' : '启动' }}
        </el-button>
        <el-button size="small" @click.stop="openConfig">
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
        <span class="mode-btn" :class="{ active: strategy.decision_mode === 'hybrid' }">
          🔀 混合模式
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
    <div v-if="isMartingale" class="config-row">
      <span class="config-label">马丁</span>
      <span style="font-size: 12px; color: var(--text-secondary)">
        {{ cycleLabel(strategy.params?.cycle || 'medium') }} ·
        加仓 {{ strategy.params?.add_trigger_value || strategy.params?.price_step_pct || 0 }}{{ valueTypeLabel(strategy.params?.add_trigger_type || 'pct') }} ·
        止盈 {{ strategy.params?.take_profit_value || strategy.params?.take_profit_pct || 0 }}{{ valueTypeLabel(strategy.params?.take_profit_type || 'pct') }}
      </span>
    </div>

    <!-- 策略统计 -->
    <div v-if="stats" class="stats-row">
      <span class="stat-item" :class="stats.total_pnl >= 0 ? 'positive' : 'negative'">
        {{ stats.total_pnl >= 0 ? '+' : '' }}{{ stats.total_pnl.toFixed(2) }} USDT
      </span>
      <span class="stat-item">
        {{ stats.win_rate }}% 胜率
      </span>
      <span class="stat-item">
        {{ stats.total_trades }} 笔
      </span>
      <span v-if="stats.active_positions > 0" class="stat-item accent">
        {{ stats.active_positions }} 持仓
      </span>
    </div>

  </div>

  <!-- 配置对话框（放在 card 外面避免点击冒泡跳转） -->
  <el-dialog
    v-model="showConfig"
    :title="`配置 — ${strategy.name}`"
    :width="isMartingale ? '760px' : '520px'"
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
        <el-radio-group v-model="editForm.decision_mode" :disabled="isMartingale">
          <el-radio value="technical">📐 纯技术指标</el-radio>
          <el-radio value="hybrid">🔀 混合模式 (指标+AI)</el-radio>
          <el-radio value="ai">🤖 AI 驱动</el-radio>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="杠杆倍数">
        <el-input-number v-model="editForm.leverage" :min="1" :max="selectedMaxLeverage" :step="1" />
        <span class="unit">x</span>
        <span v-if="isMartingale" class="field-help">
          当前交易对最大 {{ selectedMaxLeverage }}x；{{ liquidationDistanceText }}
        </span>
      </el-form-item>

      <el-form-item v-if="!isMartingale" label="每单金额">
        <el-input-number v-model="editForm.order_amount_usdt" :min="5" :step="10" />
        <span style="margin-left: 8px; color: var(--text-secondary)">USDT</span>
      </el-form-item>

      <template v-if="isMartingale">
        <el-divider content-position="left">马丁格尔参数</el-divider>

        <el-form-item label="AI 生成">
          <div class="ai-param-row">
            <el-select v-model="martingaleRiskProfile" style="width: 130px">
              <el-option label="稳健" value="conservative" />
              <el-option label="均衡" value="balanced" />
              <el-option label="进取" value="aggressive" />
            </el-select>
            <el-button :loading="generatingParams" @click="generateParamsByAI">
              生成参数
            </el-button>
          </div>
        </el-form-item>

        <div class="martingale-grid">
          <el-form-item label="周期">
            <div class="param-control">
              <el-select v-model="editForm.params.cycle">
                <el-option label="短期" value="short" />
                <el-option label="中期" value="medium" />
                <el-option label="长期" value="long" />
              </el-select>
              <span class="field-help">{{ cycleHelp(editForm.params.cycle) }}</span>
            </div>
          </el-form-item>
          <el-form-item label="方向">
            <div class="param-control">
              <el-select v-model="editForm.params.direction">
                <el-option label="双向" value="both" />
                <el-option label="只做多" value="long" />
                <el-option label="只做空" value="short" />
              </el-select>
              <span class="field-help">限制首单方向；双向会同时允许做多和做空信号</span>
            </div>
          </el-form-item>
          <el-form-item label="跌/涨加仓">
            <div class="param-control">
              <div class="value-with-type">
                <el-input-number v-model="editForm.params.add_trigger_value" :min="0.01" :step="0.1" />
                <el-radio-group v-model="editForm.params.add_trigger_type" class="unit-radio">
                  <el-radio-button value="pct">百分比 %</el-radio-button>
                  <el-radio-button value="usdt">USDT U</el-radio-button>
                </el-radio-group>
              </div>
              <span class="field-help">{{ addTriggerHelp() }}</span>
            </div>
          </el-form-item>
          <el-form-item label="周期止盈">
            <div class="param-control">
              <div class="value-with-type">
                <el-input-number v-model="editForm.params.take_profit_value" :min="0.01" :step="0.1" />
                <el-radio-group v-model="editForm.params.take_profit_type" class="unit-radio">
                  <el-radio-button value="pct">百分比 %</el-radio-button>
                  <el-radio-button value="usdt">USDT U</el-radio-button>
                </el-radio-group>
              </div>
              <span class="field-help">{{ takeProfitHelp() }}</span>
            </div>
          </el-form-item>
          <el-form-item label="投资额">
            <div class="param-control">
              <div class="readonly-value">{{ plannedPositionUsdt.toFixed(2) }} USDT</div>
              <span class="field-help">{{ maxPositionHelp() }}</span>
            </div>
          </el-form-item>
          <el-form-item label="初次保证金">
            <div class="param-control">
              <div>
                <el-input-number v-model="editForm.params.initial_margin_usdt" :min="1" :step="5" />
                <span class="unit">USDT</span>
              </div>
              <span class="field-help">首单占用的保证金</span>
            </div>
          </el-form-item>
          <el-form-item label="加仓保证金">
            <div class="param-control">
              <div>
                <el-input-number v-model="editForm.params.add_margin_usdt" :min="1" :step="5" />
                <span class="unit">USDT</span>
              </div>
              <span class="field-help">每次自动加仓单占用的保证金</span>
            </div>
          </el-form-item>
          <el-form-item label="加仓次数">
            <div class="param-control">
              <el-input-number v-model="editForm.params.max_add_count" :min="0" :max="100" />
              <span class="field-help">首单之后最多自动加仓次数</span>
            </div>
          </el-form-item>
        </div>
      </template>

      <template v-if="editForm.decision_mode === 'ai' || editForm.decision_mode === 'hybrid'">
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
</template>

<style scoped>
.stats-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 4px;
}
.stat-item {
  font-size: 12px;
  color: var(--text-secondary);
}
.stat-item.positive { color: var(--accent-green); }
.stat-item.negative { color: var(--accent-red); }
.stat-item.accent { color: var(--accent-amber); }
.ai-param-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.martingale-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 18px;
}
.value-with-type {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
  width: 100%;
}
.value-with-type :deep(.el-input-number) {
  width: 100%;
}
.unit {
  margin-left: 6px;
  color: var(--text-secondary);
  font-size: 12px;
}
.unit-radio {
  display: flex;
  width: 100%;
}
.unit-radio :deep(.el-radio-button) {
  flex: 1;
}
.unit-radio :deep(.el-radio-button__inner) {
  width: 100%;
  padding: 8px 10px;
}
.param-control {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.field-help {
  display: block;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.35;
}
.readonly-value {
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  padding: 0 11px;
  border-radius: 6px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
}
@media (max-width: 760px) {
  .martingale-grid {
    grid-template-columns: 1fr;
  }
}
</style>
