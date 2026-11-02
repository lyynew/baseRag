import { reactive } from 'vue'

export type ToastType = 'info' | 'success' | 'error'

export interface ToastItem {
  id: number
  text: string
  type: ToastType
  leaving?: boolean
}

export const toasts = reactive<ToastItem[]>([])

let seed = 0

/**
 * 轻量提示。
 * 为什么不用 ElMessage：前台界面刻意不引入 Element 的视觉语言，
 * 弹一个蓝底圆角条会立刻破坏整体调性。
 */
export function toast(text: string, type: ToastType = 'info', duration = 2600): void {
  const item: ToastItem = { id: ++seed, text, type }
  toasts.push(item)

  window.setTimeout(() => {
    item.leaving = true
    window.setTimeout(() => {
      const idx = toasts.findIndex((t) => t.id === item.id)
      if (idx >= 0) toasts.splice(idx, 1)
    }, 200)
  }, duration)
}

export const notify = {
  info: (t: string) => toast(t, 'info'),
  success: (t: string) => toast(t, 'success'),
  error: (t: string) => toast(t, 'error', 3600),
}
