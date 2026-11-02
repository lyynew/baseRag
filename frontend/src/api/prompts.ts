import http from './request'

export interface PromptItem {
  code: string
  kb_id: number
  name: string
  content: string
  variables: string[]
  description: string | null
  version: number
  source: string
  is_customized: boolean
  updated_at: string | null
  updated_by: number | null
}

export interface PromptVar {
  name: string
  desc: string
}

export interface PromptPreview {
  rendered: string
  variables: string[]
  missing: string[]
  chars: number
  tokens_estimate: number
  version: number
}

export interface PromptTestResult {
  answer: string
  model: string
  provider: string
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
  sources: number
  rendered_system: string
  version: number
}

export interface PromptVersionItem {
  version: number
  content: string
  variables: string[]
  note: string | null
  created_by: number | null
  created_at: string | null
}

export const promptApi = {
  list: () => http.get<PromptItem[]>('/admin/prompts').then((r) => r.data),
  variables: () => http.get<PromptVar[]>('/admin/prompts/variables').then((r) => r.data),
  detail: (code: string) =>
    http.get<PromptItem>(`/admin/prompts/${code}`).then((r) => r.data),
  save: (code: string, body: { content: string; note?: string; name?: string }) =>
    http.put<PromptItem>(`/admin/prompts/${code}`, body).then((r) => r.data),
  reset: (code: string) =>
    http.post<PromptItem>(`/admin/prompts/${code}/reset`).then((r) => r.data),
  versions: (code: string) =>
    http.get<PromptVersionItem[]>(`/admin/prompts/${code}/versions`).then((r) => r.data),
  rollback: (code: string, version: number) =>
    http
      .post<PromptItem>(`/admin/prompts/${code}/rollback/${version}`)
      .then((r) => r.data),
  preview: (code: string, body: { content?: string; values: Record<string, string> }) =>
    http.post<PromptPreview>(`/admin/prompts/${code}/preview`, body).then((r) => r.data),
  test: (code: string, body: { question: string; content?: string; kb_id?: number }) =>
    http
      .post<PromptTestResult>(`/admin/prompts/${code}/test`, body, { timeout: 180000 })
      .then((r) => r.data),
}
