import http, { tokenStore } from './request'

export interface ChatSession {
  id: number
  title: string
  kb_ids: number[]
  chat_provider: string | null
  chat_model: string | null
  message_count: number
  created_at: string
  updated_at: string
}

export interface Citation {
  index: number
  chunk_id: number
  doc_id: number
  score: number
  snippet: string
}

export interface ChatMessage {
  id: number
  session_id: number
  seq: number
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  provider: string | null
  model: string | null
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
  ttft_ms: number | null
  feedback: number | null
  created_at: string
}

export interface AskResult {
  message_id: number
  session_id: number
  answer: string
  citations: Citation[]
  model: string
  usage: Record<string, number>
  latency_ms: number
  retrieval: { reason: string; hits: number }
}

export type StreamEvent =
  | { type: 'retrieval'; data: { need_retrieve: boolean; reason: string; hits: unknown[] } }
  | { type: 'delta'; data: { text: string } }
  | {
      type: 'done'
      data: {
        message_id: number
        session_id: number
        citations: Citation[]
        model: string
        usage: Record<string, number>
        latency_ms: number
        ttft_ms: number | null
      }
    }
  | { type: 'error'; data: { code: string; message: string } }

export const chatApi = {
  createSession(kbIds: number[], title?: string) {
    return http
      .post<ChatSession>('/chat/sessions', { kb_ids: kbIds, title })
      .then((r) => r.data)
  },
  sessions() {
    return http.get<ChatSession[]>('/chat/sessions').then((r) => r.data)
  },
  removeSession(id: number) {
    return http.delete(`/chat/sessions/${id}`)
  },
  messages(sessionId: number) {
    return http
      .get<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`)
      .then((r) => r.data)
  },
  ask(sessionId: number, question: string) {
    return http
      .post<AskResult>(`/chat/sessions/${sessionId}/ask`, { question })
      .then((r) => r.data)
  },
  feedback(messageId: number, feedback: number | null) {
    return http.post(`/chat/messages/${messageId}/feedback`, { feedback })
  },
}

/**
 * SSE 流式问答。
 *
 * 为什么不用 axios：浏览器端 axios 基于 XHR，拿不到增量响应体；
 * 要用 fetch + ReadableStream 才能逐块读取。
 * 这也意味着 token 与错误处理要自己来一遍，不能复用拦截器。
 */
export async function askStream(
  sessionId: number,
  question: string,
  onEvent: (evt: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`/api/v1/chat/sessions/${sessionId}/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${tokenStore.access}`,
    },
    body: JSON.stringify({ question }),
    signal,
  })

  if (!resp.ok || !resp.body) {
    let message = `请求失败（${resp.status}）`
    try {
      const body = await resp.json()
      message = body?.message || message
    } catch {
      /* 非 JSON 响应，保留默认提示 */
    }
    throw new Error(message)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const flush = (block: string) => {
    let eventName = 'message'
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    if (!dataLines.length) return
    try {
      const data = JSON.parse(dataLines.join(''))
      onEvent({ type: eventName, data } as StreamEvent)
    } catch {
      /* 半包数据，忽略 */
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE 以空行分隔事件块
    let idx = buffer.indexOf('\n\n')
    while (idx !== -1) {
      flush(buffer.slice(0, idx))
      buffer = buffer.slice(idx + 2)
      idx = buffer.indexOf('\n\n')
    }
  }
  if (buffer.trim()) flush(buffer)
}
