<script setup lang="ts">
const props = withDefaults(defineProps<{
  modelValue: boolean
  title: string
  message: string
  description?: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
  loading?: boolean
}>(), {
  description: '',
  confirmText: '确认',
  cancelText: '取消',
  danger: false,
  loading: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'confirm'): void
}>()

function close() {
  if (props.loading) return
  emit('update:modelValue', false)
}

function handleVisibleChange(value: boolean) {
  if (!value && props.loading) return
  emit('update:modelValue', value)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    width="420px"
    class="confirm-dialog"
    :show-close="!loading"
    :close-on-click-modal="!loading"
    :close-on-press-escape="!loading"
    @update:model-value="handleVisibleChange"
  >
    <div class="confirm-body">
      <div class="confirm-icon" :class="{ danger }">
        <el-icon><Delete v-if="danger" /><View v-else /></el-icon>
      </div>
      <div class="confirm-copy">
        <h3>{{ title }}</h3>
        <p>{{ message }}</p>
        <span v-if="description">{{ description }}</span>
      </div>
    </div>

    <template #footer>
      <div class="confirm-footer">
        <el-button :disabled="loading" @click="close">{{ cancelText }}</el-button>
        <el-button
          :type="danger ? 'danger' : 'primary'"
          :loading="loading"
          @click="emit('confirm')"
        >
          {{ confirmText }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.confirm-body {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.confirm-icon {
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border-radius: 50%;
  color: var(--accent-amber-dark);
  background: var(--accent-amber-glow);
}

.confirm-icon.danger {
  color: var(--accent-red);
  background: var(--accent-red-bg);
}

.confirm-copy {
  min-width: 0;
}

.confirm-copy h3 {
  margin: 0 0 8px;
  color: var(--text-primary);
  font-size: 17px;
  line-height: 1.3;
}

.confirm-copy p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.6;
}

.confirm-copy span {
  display: block;
  margin-top: 8px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.confirm-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
