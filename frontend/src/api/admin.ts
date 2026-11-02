import http from './request'

export interface AdminUser {
  id: number
  username: string
  nickname: string | null
  email: string | null
  phone: string | null
  is_active: boolean
  is_superuser: boolean
  roles: string[]
  last_login_at: string | null
  last_login_ip: string | null
  locked_until: string | null
  created_at: string
}

export interface RoleItem {
  id: number
  code: string
  name: string
  description: string | null
  is_builtin: boolean
  permissions: string[]
  user_count: number
}

export interface PermissionItem {
  code: string
  name: string
  group_name: string
}

export interface ModelConfigItem {
  id: number
  provider: string
  name: string
  base_url: string
  api_key_masked: string
  model: string
  max_context: number
  max_output: number
  supports_json: boolean
  supports_stream: boolean
  enabled: boolean
  is_default: boolean
  created_at: string
}

export interface ModelTestResult {
  ok: boolean
  latency_ms: number
  reply: string
  error: string
  usage: Record<string, number>
}

export interface AuditLogItem {
  id: number
  operator_id: number | null
  operator_name: string | null
  action: string
  target_type: string | null
  target_id: number | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  ip: string | null
  result: string
  created_at: string
}

export interface UsageSummary {
  days: number
  total_calls: number
  total_prompt_tokens: number
  total_completion_tokens: number
  items: {
    scene: string
    provider: string
    model: string
    calls: number
    prompt_tokens: number
    completion_tokens: number
  }[]
}

export interface DailyUsage {
  days: number
  items: {
    date: string
    calls: number
    prompt_tokens: number
    completion_tokens: number
    chat_calls: number
  }[]
}

export const adminApi = {
  // ---------- 用户 ----------
  users(params?: { keyword?: string; is_active?: boolean; limit?: number; offset?: number }) {
    return http.get<AdminUser[]>('/users', { params }).then((r) => r.data)
  },
  createUser(payload: {
    username: string
    password: string
    nickname?: string
    email?: string
    role_codes: string[]
  }) {
    return http.post<AdminUser>('/users', payload).then((r) => r.data)
  },
  updateUser(
    id: number,
    payload: {
      nickname?: string
      email?: string
      phone?: string
      is_active?: boolean
      role_codes?: string[]
    },
  ) {
    return http.patch<AdminUser>(`/users/${id}`, payload).then((r) => r.data)
  },
  removeUser(id: number) {
    return http.delete(`/users/${id}`)
  },
  resetPassword(id: number, newPassword: string) {
    return http.post(`/users/${id}/reset-password`, { new_password: newPassword })
  },
  unlockUser(id: number) {
    return http.post(`/users/${id}/unlock`)
  },

  // ---------- 角色权限 ----------
  roles() {
    return http.get<RoleItem[]>('/roles').then((r) => r.data)
  },
  permissions() {
    return http.get<PermissionItem[]>('/permissions').then((r) => r.data)
  },
  updateRole(id: number, payload: { name?: string; description?: string; permissions?: string[] }) {
    return http.patch<RoleItem>(`/roles/${id}`, payload).then((r) => r.data)
  },

  // ---------- 模型配置 ----------
  models() {
    return http.get<ModelConfigItem[]>('/admin/models').then((r) => r.data)
  },
  createModel(payload: Record<string, unknown>) {
    return http.post<ModelConfigItem>('/admin/models', payload).then((r) => r.data)
  },
  updateModel(id: number, payload: Record<string, unknown>) {
    return http.patch<ModelConfigItem>(`/admin/models/${id}`, payload).then((r) => r.data)
  },
  removeModel(id: number) {
    return http.delete(`/admin/models/${id}`)
  },
  setDefaultModel(id: number) {
    return http.post<ModelConfigItem[]>(`/admin/models/${id}/set-default`).then((r) => r.data)
  },
  testModel(id: number) {
    return http.post<ModelTestResult>(`/admin/models/${id}/test`).then((r) => r.data)
  },

  // ---------- 审计与用量 ----------
  auditLogs(params?: { action?: string; days?: number; limit?: number; offset?: number }) {
    return http.get<AuditLogItem[]>('/admin/audit-logs', { params }).then((r) => r.data)
  },
  usage(days = 7) {
    return http.get<UsageSummary>('/admin/usage', { params: { days } }).then((r) => r.data)
  },
  usageDaily(days = 14) {
    return http.get<DailyUsage>('/admin/usage/daily', { params: { days } }).then((r) => r.data)
  },
}
