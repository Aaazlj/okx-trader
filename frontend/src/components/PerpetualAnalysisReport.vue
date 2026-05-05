<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ analysis: any }>()

const triggeredRules = computed(() => {
  return (props.analysis?.quant_rules || []).filter((rule: any) => rule.triggered)
})

const gridTradingAdvice = computed(() => props.analysis?.strategy_parameter_advice?.grid_trading || null)
const martingaleAdvice = computed(() => props.analysis?.strategy_parameter_advice?.martingale_contract || null)

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  if (value >= 100) return value.toLocaleString('en-US', { maximumFractionDigits: 2 })
  if (value >= 1) return value.toLocaleString('en-US', { maximumFractionDigits: 4 })
  return value.toLocaleString('en-US', { maximumFractionDigits: 8 })
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return value.toLocaleString('en-US', { maximumFractionDigits: 4 })
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function formatRate(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return `${(value * 100).toFixed(4)}%`
}

function formatUsdt(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return `${value.toLocaleString('en-US', { maximumFractionDigits: 2 })} USDT`
}

function formatPriceRange(lower: number | null | undefined, upper: number | null | undefined) {
  return `${formatPrice(lower)} - ${formatPrice(upper)}`
}

function cycleLabel(cycle: string | null | undefined) {
  if (cycle === 'short') return '短期'
  if (cycle === 'long') return '长期'
  return '中期'
}

function valueWithUnit(value: number | null | undefined, type: string | null | undefined) {
  if (value === null || value === undefined) return '-'
  return `${formatNumber(value)} ${type === 'usdt' ? 'U' : '%'}`
}

function scoreStatus(score: number) {
  if (score >= 80) return 'exception'
  if (score >= 60) return 'success'
  if (score >= 40) return ''
  return 'exception'
}

function gradeClass(grade: string) {
  if (grade === 'S' || grade === 'A') return 'signal-tag--green'
  if (grade === 'B') return 'signal-tag--amber'
  return 'signal-tag--red'
}

function riskClass(level: string) {
  if (level === '低') return 'signal-tag--green'
  if (level === '中') return 'signal-tag--amber'
  return 'signal-tag--red'
}
</script>

<template>
  <div class="analysis-report">
    <el-alert
      v-if="analysis.volatility_warning?.triggered"
      type="warning"
      show-icon
      :closable="false"
      :title="analysis.volatility_warning.message"
    />
    <el-alert
      v-if="analysis.data_quality_notes?.length"
      type="info"
      show-icon
      :closable="false"
      :title="analysis.data_quality_notes.join('；')"
    />

    <section class="summary-panel">
      <div class="summary-main">
        <div>
          <div class="eyebrow">{{ analysis.symbol }} · {{ analysis.created_at }}</div>
          <h2>{{ analysis.summary.one_sentence_advice }}</h2>
        </div>
        <div class="score-ring">
          <span>{{ analysis.summary.overall_score }}</span>
          <small>综合评分</small>
        </div>
      </div>
      <div class="summary-grid">
        <div class="metric">
          <span>当前价格</span>
          <strong>{{ formatPrice(analysis.summary.current_price) }}</strong>
        </div>
        <div class="metric">
          <span>24H 涨跌</span>
          <strong :class="analysis.summary.price_change_24h >= 0 ? 'positive' : 'negative'">
            {{ formatPct(analysis.summary.price_change_24h) }}
          </strong>
        </div>
        <div class="metric">
          <span>当前趋势</span>
          <strong>{{ analysis.summary.trend }}</strong>
        </div>
        <div class="metric wide">
          <span>市场状态</span>
          <strong>{{ analysis.summary.market_state }}</strong>
        </div>
        <div class="metric">
          <span>机会等级</span>
          <el-tag class="signal-tag" :class="gradeClass(analysis.summary.opportunity_grade)">
            {{ analysis.summary.opportunity_grade }}
          </el-tag>
        </div>
        <div class="metric">
          <span>风险等级</span>
          <el-tag class="signal-tag" :class="riskClass(analysis.summary.risk_level)">
            {{ analysis.summary.risk_level }}
          </el-tag>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-header">
        <h2>多维评分面板</h2>
        <span>{{ analysis.scores.interpretation }}</span>
      </div>
      <div class="score-grid">
        <div v-for="item in analysis.scores.dimensions" :key="item.key" class="score-item">
          <div class="score-top">
            <strong>{{ item.name }}</strong>
            <span>{{ item.score }} / 100 · 权重 {{ item.weight }}%</span>
          </div>
          <el-progress
            :percentage="item.score"
            :status="scoreStatus(item.score)"
            :show-text="false"
            :stroke-width="8"
          />
          <p>{{ item.explanation }}</p>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-header">
        <h2>量化规则触发明细</h2>
        <span>已触发 {{ triggeredRules.length }} 条</span>
      </div>
      <el-table :data="analysis.quant_rules" stripe size="small">
        <el-table-column label="状态" width="88">
          <template #default="{ row }">
            <el-tag v-if="!row.available" type="info" size="small">未接入</el-tag>
            <el-tag v-else-if="row.triggered" type="success" size="small">触发</el-tag>
            <el-tag v-else type="info" size="small">未触发</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="规则名称" min-width="150" />
        <el-table-column label="加减分" width="90">
          <template #default="{ row }">
            <span :class="row.score_delta >= 0 ? 'positive' : 'negative'">
              {{ row.score_delta > 0 ? '+' : '' }}{{ row.score_delta }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="规则说明" min-width="240" />
      </el-table>
    </section>

    <section class="section">
      <div class="section-header">
        <h2>趋势分析</h2>
        <span>{{ analysis.trend_analysis.analysis }}</span>
      </div>
      <div class="info-grid">
        <div><span>趋势方向</span><strong>{{ analysis.trend_analysis.direction }}</strong></div>
        <div><span>趋势强度</span><strong>{{ analysis.trend_analysis.strength }}</strong></div>
        <div><span>均线结构</span><strong>{{ analysis.trend_analysis.ma_structure }}</strong></div>
        <div><span>MACD</span><strong>{{ analysis.trend_analysis.macd_status }}</strong></div>
        <div><span>RSI</span><strong>{{ formatNumber(analysis.trend_analysis.rsi_value) }} · {{ analysis.trend_analysis.rsi_status }}</strong></div>
        <div><span>布林带位置</span><strong>{{ analysis.trend_analysis.boll_position }}</strong></div>
        <div><span>ATR 波动率</span><strong>{{ formatNumber(analysis.trend_analysis.atr_pct) }}% · {{ analysis.trend_analysis.atr_level }}</strong></div>
        <div><span>反转风险</span><strong>{{ analysis.trend_analysis.has_reversal_risk ? '存在' : '未见明显信号' }}</strong></div>
      </div>
    </section>

    <section class="section">
      <div class="section-header">
        <h2>多周期共振</h2>
        <span>{{ analysis.multi_timeframe_analysis.entry_timing_advice }}</span>
      </div>
      <div class="info-grid">
        <div><span>1D</span><strong>{{ analysis.multi_timeframe_analysis.directions['1D'] }}</strong></div>
        <div><span>4H</span><strong>{{ analysis.multi_timeframe_analysis.directions['4H'] }}</strong></div>
        <div><span>1H</span><strong>{{ analysis.multi_timeframe_analysis.directions['1H'] }}</strong></div>
        <div><span>5m</span><strong>{{ analysis.multi_timeframe_analysis.directions['5m'] }}</strong></div>
        <div><span>一致性评分</span><strong>{{ analysis.multi_timeframe_analysis.consistency_score }} / 100</strong></div>
        <div><span>共振结论</span><strong>{{ analysis.multi_timeframe_analysis.conclusion }}</strong></div>
      </div>
      <p v-if="analysis.multi_timeframe_analysis.conflict_notice" class="module-text warning-text">
        {{ analysis.multi_timeframe_analysis.conflict_notice }}
      </p>
    </section>

    <section class="section">
      <div class="section-header">
        <h2>支撑压力分析</h2>
        <span>{{ analysis.support_resistance.analysis }}</span>
      </div>
      <div class="level-grid">
        <div>
          <h3>上方压力位</h3>
          <div v-for="level in analysis.support_resistance.resistance_levels" :key="`r-${level.price}`" class="level-row">
            <strong>{{ formatPrice(level.price) }}</strong>
            <span>{{ level.source }} · {{ level.distance_pct }}%</span>
          </div>
        </div>
        <div>
          <h3>下方支撑位</h3>
          <div v-for="level in analysis.support_resistance.support_levels" :key="`s-${level.price}`" class="level-row">
            <strong>{{ formatPrice(level.price) }}</strong>
            <span>{{ level.source }} · {{ level.distance_pct }}%</span>
          </div>
        </div>
        <div>
          <h3>关键价位</h3>
          <div class="level-row">
            <strong>{{ formatPrice(analysis.support_resistance.key_breakdown_price) }}</strong>
            <span>关键失守价</span>
          </div>
          <div class="level-row">
            <strong>{{ formatPrice(analysis.support_resistance.key_breakout_price) }}</strong>
            <span>关键突破价</span>
          </div>
        </div>
      </div>
    </section>

    <section class="section split-section">
      <div>
        <div class="section-header inline">
          <h2>资金费率分析</h2>
        </div>
        <div class="info-grid compact">
          <div><span>当前费率</span><strong>{{ formatRate(analysis.funding_rate_analysis.current_rate) }}</strong></div>
          <div><span>预测费率</span><strong>{{ formatRate(analysis.funding_rate_analysis.predicted_rate) }}</strong></div>
          <div><span>历史均值</span><strong>{{ formatRate(analysis.funding_rate_analysis.history_average) }}</strong></div>
          <div><span>费率评级</span><strong>{{ analysis.funding_rate_analysis.level }}</strong></div>
        </div>
        <p class="module-text">{{ analysis.funding_rate_analysis.analysis }}</p>
      </div>
      <div>
        <div class="section-header inline">
          <h2>OI 持仓量分析</h2>
        </div>
        <div class="info-grid compact">
          <div><span>当前 OI</span><strong>{{ formatNumber(analysis.open_interest_analysis.current_oi) }}</strong></div>
          <div><span>1H 变化</span><strong>{{ formatPct(analysis.open_interest_analysis.oi_change_1h_pct) }}</strong></div>
          <div><span>24H 变化</span><strong>{{ formatPct(analysis.open_interest_analysis.oi_change_24h_pct) }}</strong></div>
          <div><span>信号类型</span><strong>{{ analysis.open_interest_analysis.signal }}</strong></div>
        </div>
        <p class="module-text">{{ analysis.open_interest_analysis.meaning }}</p>
      </div>
    </section>

    <section class="section split-section">
      <div>
        <div class="section-header inline">
          <h2>成交量分析</h2>
        </div>
        <div class="info-grid compact">
          <div><span>当前成交量</span><strong>{{ formatNumber(analysis.volume_analysis.volume) }}</strong></div>
          <div><span>20 周期均量</span><strong>{{ formatNumber(analysis.volume_analysis.average_volume_20) }}</strong></div>
          <div><span>量能倍数</span><strong>{{ formatNumber(analysis.volume_analysis.volume_ratio) }}x</strong></div>
          <div><span>量价关系</span><strong>{{ analysis.volume_analysis.relation }}</strong></div>
        </div>
        <p class="module-text">{{ analysis.volume_analysis.analysis }}</p>
      </div>
      <div>
        <div class="section-header inline">
          <h2>多空情绪分析</h2>
        </div>
        <div class="info-grid compact">
          <div><span>多空账户比</span><strong>{{ formatNumber(analysis.sentiment_analysis.long_short_account_ratio) }}</strong></div>
          <div><span>多空持仓比</span><strong>{{ formatNumber(analysis.sentiment_analysis.long_short_position_ratio) }}</strong></div>
          <div><span>主动买入</span><strong>{{ formatPct(analysis.sentiment_analysis.active_buy_pct) }}</strong></div>
          <div><span>主动卖出</span><strong>{{ formatPct(analysis.sentiment_analysis.active_sell_pct) }}</strong></div>
        </div>
        <p class="module-text">{{ analysis.sentiment_analysis.analysis }}</p>
      </div>
    </section>

    <section class="section">
      <div class="section-header">
        <h2>订单簿深度分析</h2>
        <span>{{ analysis.orderbook_depth_analysis.analysis }}</span>
      </div>
      <div class="info-grid">
        <div><span>买卖价差</span><strong>{{ formatPrice(analysis.orderbook_depth_analysis.spread) }} · {{ formatNumber(analysis.orderbook_depth_analysis.spread_pct) }}%</strong></div>
        <div><span>买盘深度</span><strong>{{ formatNumber(analysis.orderbook_depth_analysis.bid_depth) }}</strong></div>
        <div><span>卖盘深度</span><strong>{{ formatNumber(analysis.orderbook_depth_analysis.ask_depth) }}</strong></div>
        <div><span>盘口失衡</span><strong>{{ analysis.orderbook_depth_analysis.imbalance }}</strong></div>
        <div><span>买盘挂单墙</span><strong>{{ formatPrice(analysis.orderbook_depth_analysis.largest_bid_wall?.price) }}</strong></div>
        <div><span>卖盘挂单墙</span><strong>{{ formatPrice(analysis.orderbook_depth_analysis.largest_ask_wall?.price) }}</strong></div>
      </div>
    </section>

    <section class="section split-section">
      <div>
        <div class="section-header inline">
          <h2>机构行为分析</h2>
        </div>
        <div class="info-grid compact">
          <div><span>行为类型</span><strong>{{ analysis.institutional_behavior.type }}</strong></div>
          <div><span>置信度</span><strong>{{ analysis.institutional_behavior.confidence }}</strong></div>
        </div>
        <div class="module-list">
          <span v-for="item in analysis.institutional_behavior.basis" :key="item">{{ item }}</span>
        </div>
        <p class="module-text">{{ analysis.institutional_behavior.operation_hint }}</p>
      </div>
      <div>
        <div class="section-header inline">
          <h2>市场阶段识别</h2>
        </div>
        <div class="info-grid compact">
          <div><span>当前阶段</span><strong>{{ analysis.market_phase.phase }}</strong></div>
          <div><span>适合策略</span><strong>{{ analysis.market_phase.strategy_fit }}</strong></div>
        </div>
        <div class="module-list">
          <span v-for="item in analysis.market_phase.basis" :key="item">{{ item }}</span>
        </div>
        <p class="module-text">{{ analysis.market_phase.risk_notice }}</p>
      </div>
    </section>

    <section class="section">
      <div class="section-header">
        <h2>策略匹配</h2>
      </div>
      <div class="strategy-match-grid">
        <div>
          <h3>推荐策略</h3>
          <div v-for="item in analysis.strategy_match.recommended" :key="item.name" class="strategy-row">
            <strong>{{ item.name }}</strong>
            <span>{{ item.reason }}</span>
          </div>
        </div>
        <div>
          <h3>不适合策略</h3>
          <div v-for="item in analysis.strategy_match.unsuitable" :key="item.name" class="strategy-row">
            <strong>{{ item.name }}</strong>
            <span>{{ item.reason }}</span>
          </div>
        </div>
      </div>
    </section>

    <section v-if="gridTradingAdvice || martingaleAdvice" class="section split-section">
      <div v-if="gridTradingAdvice">
        <div class="section-header inline">
          <h2>网格交易参数</h2>
          <el-tag size="small" effect="plain">{{ gridTradingAdvice.suitability }}</el-tag>
        </div>
        <div class="info-grid compact">
          <div><span>价格区间</span><strong>{{ formatPriceRange(gridTradingAdvice.lower_price, gridTradingAdvice.upper_price) }}</strong></div>
          <div><span>网格数</span><strong>{{ gridTradingAdvice.grid_count }} 格</strong></div>
          <div><span>每格间距</span><strong>{{ formatNumber(gridTradingAdvice.grid_spacing_pct) }}% · {{ formatPrice(gridTradingAdvice.grid_spacing_price) }}</strong></div>
          <div><span>杠杆倍数</span><strong>{{ gridTradingAdvice.leverage }}x</strong></div>
          <div><span>网格模式</span><strong>{{ gridTradingAdvice.mode }}</strong></div>
          <div><span>保证金模式</span><strong>{{ gridTradingAdvice.margin_mode }}</strong></div>
          <div><span>下沿失效</span><strong>{{ formatPrice(gridTradingAdvice.stop_lower_price) }}</strong></div>
          <div><span>上沿失效</span><strong>{{ formatPrice(gridTradingAdvice.stop_upper_price) }}</strong></div>
        </div>
        <p class="module-text">依据：{{ gridTradingAdvice.range_basis }}</p>
        <div class="module-list">
          <span v-for="item in (gridTradingAdvice.notes || [])" :key="item">{{ item }}</span>
        </div>
      </div>
      <div v-if="martingaleAdvice">
        <div class="section-header inline">
          <h2>马丁格尔合约参数</h2>
          <el-tag size="small" effect="plain">{{ martingaleAdvice.suitability }}</el-tag>
        </div>
        <div class="info-grid compact">
          <div><span>周期</span><strong>{{ cycleLabel(martingaleAdvice.cycle) }} ({{ martingaleAdvice.bar }})</strong></div>
          <div><span>方向</span><strong>{{ martingaleAdvice.direction_label }}</strong></div>
          <div><span>跌/涨加仓</span><strong>{{ valueWithUnit(martingaleAdvice.add_trigger_value, martingaleAdvice.add_trigger_type) }} · {{ formatPrice(martingaleAdvice.add_trigger_price_delta) }}</strong></div>
          <div><span>周期止盈</span><strong>{{ valueWithUnit(martingaleAdvice.take_profit_value, martingaleAdvice.take_profit_type) }} · {{ formatPrice(martingaleAdvice.take_profit_price_delta) }}</strong></div>
          <div><span>初次保证金</span><strong>{{ formatUsdt(martingaleAdvice.initial_margin_usdt) }}</strong></div>
          <div><span>加仓保证金</span><strong>{{ formatUsdt(martingaleAdvice.add_margin_usdt) }}</strong></div>
          <div><span>最大加仓</span><strong>{{ martingaleAdvice.max_add_count }} 次</strong></div>
          <div><span>投资额模板</span><strong>{{ formatUsdt(martingaleAdvice.max_position_usdt) }}</strong></div>
          <div><span>杠杆倍数</span><strong>{{ martingaleAdvice.leverage }}x</strong></div>
          <div><span>硬止损</span><strong>{{ formatNumber(martingaleAdvice.hard_stop_pct) }}%</strong></div>
        </div>
        <div class="module-list">
          <span>单币每日最多 {{ martingaleAdvice.risk?.max_daily_per_symbol }} 次</span>
          <span>日亏损上限 {{ formatNumber(martingaleAdvice.risk?.max_daily_loss_pct) }}%</span>
          <span v-for="item in (martingaleAdvice.notes || [])" :key="item">{{ item }}</span>
        </div>
      </div>
    </section>

    <section class="section split-section">
      <div>
        <div class="section-header inline">
          <h2>风险收益比</h2>
        </div>
        <div class="info-grid compact">
          <div><span>止损区</span><strong>{{ formatPrice(analysis.risk_reward_analysis.stop_zone) }}</strong></div>
          <div><span>第一目标</span><strong>{{ formatPrice(analysis.risk_reward_analysis.target1) }}</strong></div>
          <div><span>第二目标</span><strong>{{ formatPrice(analysis.risk_reward_analysis.target2) }}</strong></div>
          <div><span>目标二 R/R</span><strong>{{ formatNumber(analysis.risk_reward_analysis.risk_reward_target2) }}</strong></div>
        </div>
        <p class="module-text">{{ analysis.risk_reward_analysis.evaluation }}</p>
      </div>
      <div>
        <div class="section-header inline">
          <h2>交易计划草稿</h2>
        </div>
        <div class="info-grid compact">
          <div><span>关注方向</span><strong>{{ analysis.trading_plan.direction }}</strong></div>
          <div><span>观察区间</span><strong>{{ analysis.trading_plan.entry_observation_zone?.map(formatPrice).join(' - ') || '-' }}</strong></div>
          <div><span>止损</span><strong>{{ formatPrice(analysis.trading_plan.stop_loss) }}</strong></div>
          <div><span>杠杆</span><strong>{{ analysis.trading_plan.leverage }}x</strong></div>
        </div>
        <p class="module-text">{{ analysis.trading_plan.invalid_condition }}</p>
        <p class="module-text warning-text">{{ analysis.trading_plan.disclaimer }}</p>
      </div>
    </section>

    <section class="section">
      <div class="section-header">
        <h2>多角色建议</h2>
      </div>
      <div class="role-grid">
        <div v-for="item in analysis.role_advice" :key="item.role" class="role-item">
          <div class="score-top">
            <strong>{{ item.role }}</strong>
            <el-tag :type="item.suitable ? 'success' : 'info'" size="small">
              {{ item.suitable ? '适合参与' : '谨慎观察' }}
            </el-tag>
          </div>
          <p>{{ item.position_advice }}</p>
          <p>{{ item.leverage_advice }} · {{ item.stop_loss_advice }}</p>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-header">
        <h2>信号冲突提示</h2>
        <span>{{ analysis.conflict_analysis.length ? `发现 ${analysis.conflict_analysis.length} 个冲突` : '暂无显著冲突' }}</span>
      </div>
      <div v-if="analysis.conflict_analysis.length" class="strategy-match-grid">
        <div v-for="item in analysis.conflict_analysis" :key="`${item.signal_a}-${item.signal_b}`" class="strategy-row">
          <strong>{{ item.signal_a }} vs {{ item.signal_b }}</strong>
          <span>{{ item.reason }}；{{ item.advice }}；确认条件：{{ item.confirmation_condition }}</span>
        </div>
      </div>
      <div v-else class="empty-state">暂无显著冲突</div>
    </section>

    <section class="section">
      <div class="section-header">
        <h2>AI 自然语言报告</h2>
        <span>{{ analysis.ai_report ? '完整版' : analysis.ai_report_error }}</span>
      </div>
      <pre v-if="analysis.ai_report" class="ai-report">{{ analysis.ai_report }}</pre>
      <div v-else class="empty-state">
        {{ analysis.ai_report_error || 'AI 报告暂不可用' }}
      </div>
    </section>
  </div>
</template>

<style scoped>
.analysis-report {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.symbol-control label,
.eyebrow,
.metric span,
.info-grid span,
.section-header span,
.score-top span,
.level-row span {
  font-size: 12px;
  color: var(--text-muted);
}

.summary-panel,
.section {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}

.summary-panel {
  padding: 22px;
}

.summary-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;
}

.summary-main h2 {
  margin: 4px 0 0;
  font-family: var(--font-display);
  font-size: 22px;
  line-height: 1.25;
  color: var(--text-primary);
}

.score-ring {
  width: 104px;
  height: 104px;
  border-radius: 50%;
  border: 8px solid var(--accent-amber-border);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
}

.score-ring span {
  font-family: var(--font-display);
  font-size: 30px;
  font-weight: 700;
}

.score-ring small {
  color: var(--text-muted);
  font-size: 11px;
}

.summary-grid,
.info-grid,
.score-grid,
.level-grid {
  display: grid;
  gap: 12px;
}

.summary-grid {
  grid-template-columns: repeat(6, minmax(120px, 1fr));
}

.metric,
.info-grid > div,
.score-item,
.level-row {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
}

.metric {
  min-height: 78px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.metric.wide {
  grid-column: span 2;
}

.metric strong,
.info-grid strong,
.level-row strong {
  color: var(--text-primary);
  font-size: 15px;
}

.signal-tag {
  width: fit-content;
  min-width: 42px;
  justify-content: center;
  border: none !important;
  color: #fff !important;
  font-weight: 700;
  letter-spacing: 0;
}

.signal-tag--green {
  background: #1f7a3a !important;
}

.signal-tag--amber {
  background: #a45f12 !important;
}

.signal-tag--red {
  background: #a83226 !important;
}

.section {
  padding: 20px 22px;
}

.section-header {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}

.section-header.inline {
  margin-bottom: 10px;
}

.section-header h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 17px;
  color: var(--text-primary);
}

.score-grid {
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
}

.score-item {
  padding: 14px;
  display: grid;
  gap: 8px;
}

.score-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.score-item p,
.module-text {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.warning-text {
  color: var(--accent-orange);
  margin-top: 10px;
}

.info-grid {
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.info-grid.compact {
  grid-template-columns: repeat(2, minmax(160px, 1fr));
  margin-bottom: 12px;
}

.info-grid > div {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.level-grid {
  grid-template-columns: 1fr 1fr 1fr;
}

.level-grid h3 {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.level-row {
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.split-section {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 22px;
}

.module-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.module-list span {
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-size: 12px;
}

.strategy-match-grid,
.role-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}

.strategy-match-grid h3 {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.strategy-row,
.role-item {
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  display: grid;
  gap: 5px;
}

.strategy-row span,
.role-item p {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
  margin: 0;
}

.ai-report {
  margin: 0;
  padding: 16px;
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  font-family: var(--font-body);
  font-size: 14px;
  line-height: 1.8;
  white-space: pre-wrap;
}

.positive {
  color: var(--accent-green) !important;
}

.negative {
  color: var(--accent-red) !important;
}

@media (max-width: 980px) {
  .summary-grid,
  .level-grid,
  .split-section {
    grid-template-columns: 1fr;
  }

  .metric.wide {
    grid-column: span 1;
  }
}

@media (max-width: 640px) {
  .summary-main {
    align-items: stretch;
    flex-direction: column;
  }

  .score-ring {
    width: 92px;
    height: 92px;
  }
}
</style>
