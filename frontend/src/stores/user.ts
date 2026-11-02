import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { authApi, type UserInfo } from '@/api/auth'
import { tokenStore } from '@/api/request'

export const useUserStore = defineStore('user', () => {
  const user = ref<UserInfo | null>(null)
  const loading = ref(false)

  const isLoggedIn = computed(() => Boolean(tokenStore.access))
  const permissions = computed(() => user.value?.permissions ?? [])
  const isSuperuser = computed(() => user.value?.is_superuser ?? false)
  const displayName = computed(() => user.value?.nickname || user.value?.username || '')
  const roleNames = computed(() => (user.value?.roles ?? []).map((r) => r.name))

  /** 权限判定：传数组时任一命中即通过（与后端 require_perm 的默认 all 语义不同，
   *  前端只用于菜单显隐，真正的拦截在后端） */
  function hasPerm(code?: string | string[]): boolean {
    if (!code) return true
    if (isSuperuser.value) return true
    const codes = Array.isArray(code) ? code : [code]
    return codes.some((c) => permissions.value.includes(c))
  }

  async function login(username: string, password: string): Promise<void> {
    loading.value = true
    try {
      const tokens = await authApi.login({ username, password })
      tokenStore.set(tokens.access_token, tokens.refresh_token)
      await fetchMe()
    } finally {
      loading.value = false
    }
  }

  async function fetchMe(): Promise<void> {
    user.value = await authApi.me()
  }

  async function logout(): Promise<void> {
    try {
      if (tokenStore.refresh) await authApi.logout(tokenStore.refresh)
    } catch {
      // 登出失败也要清理本地状态，否则用户会卡在"登不出去"
    } finally {
      reset()
    }
  }

  function reset(): void {
    user.value = null
    tokenStore.clear()
  }

  return {
    user,
    loading,
    isLoggedIn,
    permissions,
    isSuperuser,
    displayName,
    roleNames,
    hasPerm,
    login,
    fetchMe,
    logout,
    reset,
  }
})
