<script setup lang="ts">
import { useTradingStore } from '../stores/trading'
import StrategyCard from '../components/StrategyCard.vue'
import PositionList from '../components/PositionList.vue'
import LogViewer from '../components/LogViewer.vue'

const store = useTradingStore()
</script>

<template>
  <div class="dashboard">
    <!-- 账户统计 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="label">总权益</div>
        <div class="value">{{ store.account.total_equity.toFixed(2) }} USDT</div>
      </div>
      <div class="stat-card">
        <div class="label">可用余额</div>
        <div class="value">{{ store.account.available_balance.toFixed(2) }} USDT</div>
      </div>
      <div class="stat-card">
        <div class="label">未实现盈亏</div>
        <div
          class="value"
          :class="store.account.unrealized_pnl >= 0 ? 'positive' : 'negative'"
        >
          {{ store.account.unrealized_pnl >= 0 ? '+' : '' }}{{ store.account.unrealized_pnl.toFixed(2) }} USDT
        </div>
      </div>
      <div class="stat-card">
        <div class="label">运行中策略</div>
        <div class="value">
          {{ store.strategies.filter((s) => s.is_active).length }} / {{ store.strategies.length }}
        </div>
      </div>
      <div class="stat-card">
        <div class="label">当前持仓</div>
        <div class="value">{{ store.positions.length }}</div>
      </div>
    </div>

    <!-- 策略面板 -->
    <div class="section">
      <div class="section-header">
        <h2>⚙️ 策略管理</h2>
        <el-button size="small" @click="store.fetchStrategies()">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
      <div class="section-body">
        <div class="strategy-grid">
          <StrategyCard
            v-for="strategy in store.strategies"
            :key="strategy.id"
            :strategy="strategy"
          />
        </div>
      </div>
    </div>

    <!-- 持仓列表 -->
    <div class="section">
      <div class="section-header">
        <h2>📊 当前持仓</h2>
      </div>
      <div class="section-body">
        <PositionList :positions="store.positions" />
      </div>
    </div>

    <!-- 实时日志 -->
    <div class="section">
      <div class="section-header">
        <h2>📋 实时日志</h2>
        <span style="font-size: 12px; color: var(--text-muted)">
          {{ store.logs.length }} 条记录
        </span>
      </div>
      <div class="section-body">
        <LogViewer :logs="store.logs" />
      </div>
    </div>
  </div>
</template>
