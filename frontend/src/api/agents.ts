import http from './request'

export interface AgentItem {
  id: number
  name: string
  description: string | null
  emoji: string
  kb_ids: number[]
  kb_names: string[]
  provider: string | null
  model: string | null
  prompt_overrides: Record<string, string>
  retrieve_config: Record<string, unknown>
  gen_settings: Record<string, unknown>
  is_published: boolean
  is_public: boolean
  session_count: number
  message_count: number
  owner_id: number
  created_at: string | null
  updated_at: string | null
}

export interface AgentBrief {
  id: number
  name: string
  description: string | null
  emoji: string
  kb_count: number
  model: string | null
  is_public: boolean
}

export interface AgentTestResult {
  answer: string
  model: string
  provider: string
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
  sources: number
  citations: { index: number; doc_id: number; score: number; snippet: string }[]
  system_prompt_head: string
}

export interface AgentPayload {
  name: string
  description?: string | null
  emoji?: string
  kb_ids: number[]
  provider?: string | null
  model?: string | null
  prompt_overrides?: Record<string, string>
  retrieve_config?: Record<string, unknown>
  gen_settings?: Record<string, unknown>
  is_published?: boolean
  is_public?: boolean
}

export const agentApi = {
  // 后台
  adminList: () => http.get<AgentItem[]>('/admin/agents').then((r) => r.data),
  adminGet: (id: number) => http.get<AgentItem>(`/admin/agents/${id}`).then((r) => r.data),
  adminCreate: (body: AgentPayload) =>
    http.post<AgentItem>('/admin/agents', body).then((r) => r.data),
  adminUpdate: (id: number, body: Partial<AgentPayload>) =>
    http.patch<AgentItem>(`/admin/agents/${id}`, body).then((r) => r.data),
  adminDelete: (id: number) => http.delete(`/admin/agents/${id}`).then((r) => r.data),
  adminPublish: (id: number, published: boolean) =>
    http
      .post<AgentItem>(`/admin/agents/${id}/publish`, null, { params: { published } })
      .then((r) => r.data),
  adminTest: (id: number, question: string) =>
    http
      .post<AgentTestResult>(`/admin/agents/${id}/test`, { question }, { timeout: 180000 })
      .then((r) => r.data),

  // 前台
  listMine: () => http.get<AgentBrief[]>('/agents').then((r) => r.data),
}
