import http from './request'

export interface ChunkConfig {
  strategy: 'recursive' | 'markdown_header' | 'fixed'
  chunk_size: number
  chunk_overlap: number
  min_chunk_size: number
  keep_table_intact: boolean
}

export interface RetrieveConfig {
  top_k: number
  rerank_top_n: number
  score_threshold: number
  rerank_enabled: boolean
}

export interface KnowledgeBase {
  id: number
  name: string
  description: string | null
  owner_id: number
  embedding_model: string
  embedding_dim: number
  chunk_config: Partial<ChunkConfig>
  retrieve_config: Partial<RetrieveConfig>
  sensitivity: 'normal' | 'confidential'
  doc_count: number
  chunk_count: number
  total_size_bytes: number
  created_at: string
  updated_at: string
  my_role: string | null
}

export interface DocumentItem {
  id: number
  kb_id: number
  name: string
  file_ext: string
  file_size: number
  status:
    | 'pending'
    | 'parsing'
    | 'splitting'
    | 'embedding'
    | 'ready'
    | 'failed'
    | 'no_text_layer'
  error_msg: string | null
  no_text_layer: boolean
  page_count: number
  char_count: number
  chunk_count: number
  created_at: string
  updated_at: string
}

export interface IngestTask {
  id: number
  kb_id: number
  doc_id: number | null
  task_type: string
  status: 'queued' | 'running' | 'success' | 'failed' | 'canceled'
  progress: number
  total_items: number
  processed_items: number
  error_msg: string | null
  started_at: string | null
  finished_at: string | null
}

export interface UploadResult {
  document: DocumentItem
  task: IngestTask
  duplicated: boolean
}

export interface SearchHit {
  chunk_id: number
  doc_id: number
  doc_name: string | null
  content: string
  score: number
  vector_score: number | null
  section_path: string | null
}

export interface SearchResult {
  query: string
  hits: SearchHit[]
  vector_hits: number
  rerank_applied: boolean
  tokens: number
}

export const kbApi = {
  list(keyword?: string) {
    return http
      .get<KnowledgeBase[]>('/kb', { params: keyword ? { keyword } : {} })
      .then((r) => r.data)
  },
  get(id: number) {
    return http.get<KnowledgeBase>(`/kb/${id}`).then((r) => r.data)
  },
  create(payload: {
    name: string
    description?: string
    sensitivity?: string
    chunk_config?: Partial<ChunkConfig>
    retrieve_config?: Partial<RetrieveConfig>
  }) {
    return http.post<KnowledgeBase>('/kb', payload).then((r) => r.data)
  },
  update(id: number, payload: Record<string, unknown>) {
    return http.patch<KnowledgeBase>(`/kb/${id}`, payload).then((r) => r.data)
  },
  remove(id: number) {
    return http.delete(`/kb/${id}`)
  },
  search(id: number, query: string, rerank = true) {
    return http
      .post<SearchResult>(`/kb/${id}/search`, { query, rerank })
      .then((r) => r.data)
  },

  // ---------- 文档 ----------
  documents(kbId: number, params?: { status?: string; keyword?: string }) {
    return http
      .get<DocumentItem[]>(`/kb/${kbId}/documents`, { params })
      .then((r) => r.data)
  },
  getDocument(docId: number) {
    return http.get<DocumentItem>(`/kb/documents/${docId}`).then((r) => r.data)
  },
  upload(kbId: number, file: File, onProgress?: (percent: number) => void) {
    const form = new FormData()
    form.append('file', file)
    return http
      .post<UploadResult>(`/kb/${kbId}/documents`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 600000,
        onUploadProgress: (e) => {
          if (onProgress && e.total) {
            onProgress(Math.round((e.loaded / e.total) * 100))
          }
        },
      })
      .then((r) => r.data)
  },
  removeDocument(docId: number) {
    return http.delete(`/kb/documents/${docId}`)
  },
  reindex(docId: number) {
    return http.post<IngestTask>(`/kb/documents/${docId}/reindex`).then((r) => r.data)
  },
  task(taskId: number) {
    return http.get<IngestTask>(`/kb/tasks/${taskId}`).then((r) => r.data)
  },
  chunks(kbId: number, docId: number, limit = 20) {
    return http
      .get<{
        doc_id: number
        total: number
        items: {
          id: number
          index: number
          section_path: string | null
          char_count: number
          embedded: boolean
          content: string
        }[]
      }>(`/kb/${kbId}/chunks/${docId}`, { params: { limit } })
      .then((r) => r.data)
  },
}
