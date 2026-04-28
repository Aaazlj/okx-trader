<script setup lang="ts">
import type { LogEntry } from '../stores/trading'

defineProps<{ logs: LogEntry[] }>()
</script>

<template>
  <div v-if="logs.length === 0" class="empty-state">
    <div class="icon">📝</div>
    <div>暂无日志</div>
  </div>
  <div v-else class="log-viewer">
    <div
      v-for="(log, i) in logs"
      :key="i"
      class="log-entry"
      :class="log.type"
    >
      <span class="log-time">{{ log.time }}</span>
      <span>{{ log.message }}</span>
    </div>
  </div>
</template>
