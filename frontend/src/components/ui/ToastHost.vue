<template>
  <Teleport to="body">
    <div class="toast-host">
      <TransitionGroup name="toast">
        <div v-for="t in toasts" :key="t.id" class="toast" :class="[t.type, { leaving: t.leaving }]">
          <span class="dot" />
          <span class="text">{{ t.text }}</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { toasts } from '@/utils/toast'
</script>

<style scoped>
.toast-host {
  position: fixed;
  left: 50%;
  bottom: 36px;
  transform: translateX(-50%);
  z-index: 3000;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 16px;
  border-radius: 12px;
  background: rgba(23, 24, 26, 0.94);
  color: #f6f5f3;
  font-size: 13px;
  line-height: 1.4;
  box-shadow:
    0 1px 2px rgba(0, 0, 0, 0.16),
    0 12px 32px rgba(0, 0, 0, 0.24);
  backdrop-filter: blur(10px);
  max-width: 420px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #9aa0a6;
  flex-shrink: 0;
}

.toast.success .dot {
  background: #5cc98f;
}

.toast.error .dot {
  background: #ef6b6b;
}

.text {
  word-break: break-word;
}

.toast-enter-active {
  transition:
    opacity 0.22s ease,
    transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
}

.toast-leave-active {
  transition:
    opacity 0.18s ease,
    transform 0.18s ease;
  position: absolute;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(10px) scale(0.98);
}

.toast-move {
  transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
}
</style>
