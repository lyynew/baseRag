<template>
  <Teleport to="body">
    <Transition name="mask">
      <div v-if="open" class="ui-mask" @click.self="close">
        <Transition name="panel" appear>
          <div v-if="open" class="ui-panel" :style="{ width }" role="dialog">
            <header class="ui-panel-head">
              <h3>{{ title }}</h3>
              <button class="ui-close" type="button" aria-label="关闭" @click="close">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none">
                  <path
                    d="M6 6l12 12M18 6L6 18"
                    stroke="currentColor"
                    stroke-width="1.9"
                    stroke-linecap="round"
                  />
                </svg>
              </button>
            </header>

            <div class="ui-panel-body">
              <slot />
            </div>

            <footer v-if="$slots.footer" class="ui-panel-foot">
              <slot name="footer" />
            </footer>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ open: boolean; title?: string; width?: string }>(), {
  title: '',
  width: '460px',
})

const emit = defineEmits<{ (e: 'update:open', v: boolean): void }>()

function close() {
  emit('update:open', false)
}
</script>

<style scoped>
.ui-mask {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(23, 24, 26, 0.32);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
}

.ui-panel {
  max-width: 100%;
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  background: var(--surface, #fff);
  border-radius: 18px;
  box-shadow:
    0 1px 2px rgba(23, 24, 26, 0.06),
    0 24px 64px rgba(23, 24, 26, 0.18);
  overflow: hidden;
}

.ui-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 22px 12px;
}

.ui-panel-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--ink, #17181a);
}

.ui-close {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--ink-3, #9aa0a6);
  cursor: pointer;
  transition:
    background 0.16s ease,
    color 0.16s ease;
}

.ui-close:hover {
  background: #f2f1ee;
  color: var(--ink, #17181a);
}

.ui-panel-body {
  padding: 0 22px 8px;
  overflow-y: auto;
}

.ui-panel-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 22px 20px;
}

/* 过渡：遮罩淡入，面板轻微放大，模拟"浮出"的物理感 */
.mask-enter-active,
.mask-leave-active {
  transition: opacity 0.2s ease;
}
.mask-enter-from,
.mask-leave-to {
  opacity: 0;
}

.panel-enter-active {
  transition:
    opacity 0.24s cubic-bezier(0.2, 0.8, 0.2, 1),
    transform 0.24s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.panel-leave-active {
  transition:
    opacity 0.14s ease,
    transform 0.14s ease;
}
.panel-enter-from {
  opacity: 0;
  transform: scale(0.96) translateY(8px);
}
.panel-leave-to {
  opacity: 0;
  transform: scale(0.98);
}
</style>
