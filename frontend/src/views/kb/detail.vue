<template>
  <div class="page" v-loading="loading">
    <div class="head">
      <div class="head-left">
        <el-button link @click="router.push('/admin/kb')">
          <el-icon><ArrowLeft /></el-icon>&nbsp;返回
        </el-button>
        <h2 class="page-title">{{ kb?.name || '知识库' }}</h2>
        <el-tag v-if="kb?.sensitivity === 'confidential'" type="danger" size="small" effect="plain">
          涉密
        </el-tag>
      </div>
      <div class="head-right">
        <el-button v-if="canWrite" @click="openSettings">
          <el-icon><Setting /></el-icon>&nbsp;设置
        </el-button>
        <el-button @click="openSearch">
          <el-icon><Search /></el-icon>&nbsp;检索测试
        </el-button>
      </div>
    </div>

    <el-descriptions v-if="kb" :column="4" size="small" class="desc">
      <el-descriptions-item label="向量模型">{{ kb.embedding_model }}</el-descriptions-item>
      <el-descriptions-item label="维度">{{ kb.embedding_dim }}</el-descriptions-item>
      <el-descriptions-item label="切片策略">
        {{ (kb.chunk_config?.strategy as string) || 'recursive' }} /
        {{ kb.chunk_config?.chunk_size || '-' }} 字
      </el-descriptions-item>
      <el-descriptions-item label="文档 / 切片">
        {{ kb.doc_count }} / {{ kb.chunk_count }}
      </el-descriptions-item>
    </el-descriptions>

    <el-card shadow="never" class="upload-card">
      <el-upload
        drag
        multiple
        :show-file-list="false"
        :http-request="doUpload"
        :before-upload="beforeUpload"
        :disabled="!canWrite"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          拖拽文件到此处，或 <em>点击选择</em>
        </div>
        <template #tip>
          <div class="text-muted" style="margin-top: 6px">
            支持 PDF / Word / Markdown / TXT / Excel，单文件 ≤ 200MB。
            扫描件与图片当前不支持（无 OCR）。
          </div>
        </template>
      </el-upload>

      <div v-if="uploads.length" class="upload-list">
        <div v-for="u in uploads" :key="u.key" class="upload-item">
          <span class="upload-name">{{ u.name }}</span>
          <el-progress
            :percentage="u.percent"
            :status="u.status === 'failed' ? 'exception' : undefined"
            :stroke-width="6"
            style="flex: 1; margin: 0 12px"
          />
          <span class="upload-state">{{ uploadLabel(u) }}</span>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <template #header>
        <div class="flex-between">
          <span>文档列表</span>
          <div>
            <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 130px" @change="loadDocs">
              <el-option label="可用" value="ready" />
              <el-option label="处理中" value="embedding" />
              <el-option label="失败" value="failed" />
              <el-option label="无文本层" value="no_text_layer" />
            </el-select>
            <el-button style="margin-left: 8px" @click="loadDocs">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table :data="docs" size="small" empty-text="暂无文档">
        <el-table-column prop="name" label="文件名" min-width="220" show-overflow-tooltip />
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="150">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.error_msg"
              :content="row.error_msg"
              placement="top"
              effect="dark"
            >
              <el-tag :type="statusType(row.status)" size="small">
                {{ statusLabel(row.status) }}
              </el-tag>
            </el-tooltip>
            <el-tag v-else :type="statusType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="切片" width="80" />
        <el-table-column prop="char_count" label="字符" width="90" />
        <el-table-column label="上传时间" width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="viewChunks(row)">切片</el-button>
            <el-button
              link
              type="primary"
              size="small"
              :disabled="!canWrite"
              @click="reindex(row)"
            >
              重建
            </el-button>
            <el-button link type="danger" size="small" :disabled="!canWrite" @click="removeDoc(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 切片预览 -->
    <el-drawer v-model="chunkVisible" title="切片预览" size="620px">
      <div v-loading="chunkLoading">
        <p class="text-muted">
          共 {{ chunkTotal }} 个切片，显示前 {{ chunkItems.length }} 个
        </p>
        <el-card v-for="c in chunkItems" :key="c.id" shadow="never" class="chunk-card">
          <div class="chunk-head">
            <span class="chunk-idx">#{{ c.index }}</span>
            <el-tag v-if="c.section_path" size="small" effect="plain">{{ c.section_path }}</el-tag>
            <span class="text-muted">{{ c.char_count }} 字</span>
            <el-tag :type="c.embedded ? 'success' : 'info'" size="small">
              {{ c.embedded ? '已向量化' : '未向量化' }}
            </el-tag>
          </div>
          <div class="chunk-body">{{ c.content }}</div>
        </el-card>
      </div>
    </el-drawer>

    <!-- 检索测试 -->
    <el-drawer v-model="searchVisible" title="检索测试（不含生成）" size="620px">
      <div class="search-bar">
        <el-input
          v-model="searchQuery"
          placeholder="输入一个问题，看看会召回哪些片段"
          @keyup.enter="doSearch"
        >
          <template #append>
            <el-button :loading="searchLoading" @click="doSearch">检索</el-button>
          </template>
        </el-input>
      </div>
      <p v-if="searchResult" class="text-muted">
        召回 {{ searchResult.vector_hits }} 条 · {{ searchResult.rerank_applied ? '已精排' : '未精排' }}
        · 消耗 {{ searchResult.tokens }} token
      </p>
      <el-card v-for="(h, i) in searchResult?.hits || []" :key="h.chunk_id" shadow="never" class="chunk-card">
        <div class="chunk-head">
          <span class="chunk-idx">[{{ i + 1 }}]</span>
          <el-tag size="small" effect="plain">{{ h.doc_name || `文档 ${h.doc_id}` }}</el-tag>
          <el-tag v-if="h.section_path" size="small" type="info" effect="plain">
            {{ h.section_path }}
          </el-tag>
          <span class="text-muted">score {{ h.score }}</span>
        </div>
        <div class="chunk-body">{{ h.content }}</div>
      </el-card>
      <el-empty v-if="searchResult && searchResult.hits.length === 0" description="没有召回任何片段" />
    </el-drawer>

    <!-- 知识库设置 -->
    <el-dialog v-model="settingsVisible" title="知识库设置" width="620px" destroy-on-close>
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="修改切片参数后，已入库文档的切片会与新参数不一致，需要重建才能生效（会产生 embedding 费用）。"
        style="margin-bottom: 16px"
      />

      <el-form :model="settings" label-width="110px">
        <el-divider content-position="left">基本信息</el-divider>
        <el-form-item label="名称">
          <el-input v-model="settings.name" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="settings.description" type="textarea" :rows="2" maxlength="200" />
        </el-form-item>
        <el-form-item label="密级">
          <el-radio-group v-model="settings.sensitivity">
            <el-radio value="normal">普通</el-radio>
            <el-radio value="confidential">涉密（不应发送公有云）</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-divider content-position="left">切片参数</el-divider>
        <el-form-item label="切片策略">
          <el-select v-model="settings.strategy" style="width: 100%">
            <el-option label="按标题切分（markdown_header，推荐）" value="markdown_header" />
            <el-option label="自定义标记（delimiter）" value="delimiter" />
            <el-option label="递归切分（recursive）" value="recursive" />
            <el-option label="固定长度（fixed）" value="fixed" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="settings.strategy === 'delimiter'" label="切分标记">
          <el-input
            v-model="settings.delimiter"
            placeholder="如 <!-- chunk --> 或 ## ，按行首匹配"
            maxlength="64"
          />
          <span class="text-muted" style="margin-left: 8px">
            文档中出现该标记的位置就是切片边界，之间不再做语义合并
          </span>
        </el-form-item>
        <el-form-item label="切片长度">
          <el-input-number v-model="settings.chunk_size" :min="100" :max="4000" :step="50" />
          <span class="text-muted" style="margin-left: 8px">字符</span>
        </el-form-item>
        <el-form-item label="重叠长度">
          <el-input-number v-model="settings.chunk_overlap" :min="0" :max="500" :step="10" />
          <span class="text-muted" style="margin-left: 8px">建议为切片长度的 10%~15%</span>
        </el-form-item>
        <el-form-item label="最小碎片">
          <el-input-number v-model="settings.min_chunk_size" :min="0" :max="500" :step="10" />
          <span class="text-muted" style="margin-left: 8px">低于此长度会合并到上一块</span>
        </el-form-item>
        <el-form-item label="保护表格">
          <el-switch v-model="settings.keep_table_intact" />
          <span class="text-muted" style="margin-left: 8px">开启后 Markdown 表格不会被切断</span>
        </el-form-item>
        <el-form-item label="保护代码块">
          <el-switch v-model="settings.keep_code_intact" />
          <span class="text-muted" style="margin-left: 8px">
            超长代码按行分片，每片补回围栏与语言标记
          </span>
        </el-form-item>
        <el-form-item label="标题注入">
          <el-switch v-model="settings.keep_heading" />
          <span class="text-muted" style="margin-left: 8px">
            每个切片开头带上所属标题，脱离文档后仍可自解释
          </span>
        </el-form-item>

        <el-divider content-position="left">检索参数</el-divider>
        <el-form-item label="召回条数">
          <el-input-number v-model="settings.top_k" :min="1" :max="100" />
          <span class="text-muted" style="margin-left: 8px">送入精排的候选数，越多 rerank 越贵</span>
        </el-form-item>
        <el-form-item label="精排保留">
          <el-input-number v-model="settings.rerank_top_n" :min="1" :max="30" />
          <span class="text-muted" style="margin-left: 8px">最终喂给模型的前 N 条</span>
        </el-form-item>
        <el-form-item label="相似度阈值">
          <el-input-number
            v-model="settings.score_threshold"
            :min="0"
            :max="1"
            :step="0.05"
            :precision="2"
          />
          <span class="text-muted" style="margin-left: 8px">仅对纯向量检索生效</span>
        </el-form-item>
        <el-form-item label="启用精排">
          <el-switch v-model="settings.rerank_enabled" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="settingsVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingSettings" @click="saveSettings">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type UploadRequestOptions } from 'element-plus'
import { ArrowLeft, Search, Setting, UploadFilled } from '@element-plus/icons-vue'

import {
  kbApi,
  type DocumentItem,
  type IngestTask,
  type KnowledgeBase,
  type SearchResult,
} from '@/api/kb'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const kbId = computed(() => Number(route.params.id))
const kb = ref<KnowledgeBase | null>(null)
const docs = ref<DocumentItem[]>([])
const loading = ref(false)
const statusFilter = ref('')

interface UploadItem {
  key: string
  name: string
  percent: number
  status: 'uploading' | 'processing' | 'done' | 'failed'
  taskId?: number
  error?: string
}
const uploads = ref<UploadItem[]>([])

const canWrite = computed(() => store.hasPerm('kb:write') || kb.value?.my_role === 'owner')

// ---------------- 知识库设置 ----------------
const settingsVisible = ref(false)
const savingSettings = ref(false)

const settings = reactive({
  name: '',
  description: '',
  sensitivity: 'normal' as 'normal' | 'confidential',
  strategy: 'recursive' as 'markdown_header' | 'recursive' | 'fixed' | 'delimiter',
  delimiter: '',
  chunk_size: 512,
  chunk_overlap: 64,
  min_chunk_size: 30,
  keep_table_intact: true,
  keep_code_intact: true,
  keep_heading: true,
  top_k: 30,
  rerank_top_n: 8,
  score_threshold: 0.2,
  rerank_enabled: true,
})

function openSettings() {
  const current = kb.value
  if (!current) return
  const cc = (current.chunk_config || {}) as Record<string, unknown>
  const rc = (current.retrieve_config || {}) as Record<string, unknown>

  Object.assign(settings, {
    name: current.name,
    description: current.description || '',
    sensitivity: current.sensitivity,
    strategy: (cc.strategy as typeof settings.strategy) ?? 'recursive',
    delimiter: String(cc.delimiter ?? ''),
    chunk_size: Number(cc.chunk_size ?? 512),
    chunk_overlap: Number(cc.chunk_overlap ?? 64),
    min_chunk_size: Number(cc.min_chunk_size ?? 30),
    keep_table_intact: Boolean(cc.keep_table_intact ?? true),
    keep_code_intact: Boolean(cc.keep_code_intact ?? true),
    keep_heading: Boolean(cc.keep_heading ?? true),
    top_k: Number(rc.top_k ?? 30),
    rerank_top_n: Number(rc.rerank_top_n ?? 8),
    score_threshold: Number(rc.score_threshold ?? 0.2),
    rerank_enabled: Boolean(rc.rerank_enabled ?? true),
  })
  settingsVisible.value = true
}

async function saveSettings() {
  const current = kb.value
  if (!current) return

  const nextChunk = {
    strategy: settings.strategy,
    chunk_size: settings.chunk_size,
    chunk_overlap: settings.chunk_overlap,
    min_chunk_size: settings.min_chunk_size,
    keep_table_intact: settings.keep_table_intact,
  }
  // 只有切片参数变了才需要重建，改名字/阈值不用
  const chunkChanged = JSON.stringify(nextChunk) !== JSON.stringify(current.chunk_config || {})

  savingSettings.value = true
  try {
    await kbApi.update(kbId.value, {
      name: settings.name,
      description: settings.description,
      sensitivity: settings.sensitivity,
      chunk_config: nextChunk,
      retrieve_config: {
        top_k: settings.top_k,
        rerank_top_n: settings.rerank_top_n,
        score_threshold: settings.score_threshold,
        rerank_enabled: settings.rerank_enabled,
      },
    })
    ElMessage.success('已保存')
    settingsVisible.value = false
    await loadKb()
  } finally {
    savingSettings.value = false
  }

  if (!chunkChanged || docs.value.length === 0) return

  try {
    await ElMessageBox.confirm(
      '切片参数已变更，已有切片与新参数不一致，需要重建才能生效。是否立即重建全部文档？',
      '需要重建',
      { type: 'warning', confirmButtonText: '立即重建', cancelButtonText: '稍后手动' },
    )
  } catch {
    return
  }
  await rebuildAll()
}

async function rebuildAll() {
  const targets = docs.value.filter((d) => d.status === 'ready' || d.status === 'failed')
  if (!targets.length) {
    ElMessage.info('没有需要重建的文档')
    return
  }

  const tip = ElMessage({ message: `正在提交 ${targets.length} 个重建任务…`, duration: 0 })
  let submitted = 0
  for (const doc of targets) {
    try {
      await kbApi.reindex(doc.id)
      submitted += 1
    } catch {
      // 单个失败不阻断其余文档
    }
    // 串行提交并留间隔，避免瞬间打满队列与 embedding 限流
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  tip.close()
  ElMessage.success(`已提交 ${submitted}/${targets.length} 个重建任务`)
  await loadDocs()
}

const chunkVisible = ref(false)
const chunkLoading = ref(false)
const chunkItems = ref<
  { id: number; index: number; section_path: string | null; char_count: number; embedded: boolean; content: string }[]
>([])
const chunkTotal = ref(0)

const searchVisible = ref(false)
const searchQuery = ref('')
const searchLoading = ref(false)
const searchResult = ref<SearchResult | null>(null)

let timer: number | undefined

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function formatTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const STATUS_MAP: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  pending: { label: '排队中', type: 'info' },
  parsing: { label: '解析中', type: 'warning' },
  splitting: { label: '切片中', type: 'warning' },
  embedding: { label: '向量化中', type: 'warning' },
  ready: { label: '可用', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  no_text_layer: { label: '无文本层', type: 'danger' },
}

function statusLabel(s: string): string {
  return STATUS_MAP[s]?.label || s
}
function statusType(s: string) {
  return STATUS_MAP[s]?.type || 'info'
}

function uploadLabel(u: UploadItem): string {
  if (u.status === 'uploading') return `上传 ${u.percent}%`
  if (u.status === 'processing') return '解析入库中'
  if (u.status === 'done') return '完成'
  return u.error || '失败'
}

async function loadKb() {
  kb.value = await kbApi.get(kbId.value)
}

async function loadDocs() {
  docs.value = await kbApi.documents(kbId.value, {
    status: statusFilter.value || undefined,
  })
}

function beforeUpload(file: File): boolean {
  const ok = /\.(pdf|docx|doc|md|markdown|txt|xlsx|xls|csv)$/i.test(file.name)
  if (!ok) {
    ElMessage.error('不支持的文件类型')
    return false
  }
  if (file.size > 200 * 1024 * 1024) {
    ElMessage.error('文件超过 200MB')
    return false
  }
  return true
}

async function doUpload(options: UploadRequestOptions) {
  const file = options.file as File
  const key = `${file.name}-${Date.now()}`
  const item: UploadItem = { key, name: file.name, percent: 0, status: 'uploading' }
  uploads.value.unshift(item)

  try {
    const res = await kbApi.upload(kbId.value, file, (p) => {
      item.percent = p
    })
    item.percent = 100
    item.status = 'processing'
    item.taskId = res.task.id
    pollTask(item)
  } catch (e) {
    item.status = 'failed'
    item.error = (e as Error).message
  }
}

function pollTask(item: UploadItem) {
  const taskId = item.taskId
  if (!taskId) return

  const tick = async () => {
    try {
      const task: IngestTask = await kbApi.task(taskId)
      if (task.status === 'success') {
        item.status = 'done'
        await Promise.all([loadDocs(), loadKb()])
        // 上传列表 10 秒后自动淡出，避免堆积
        setTimeout(() => {
          uploads.value = uploads.value.filter((u) => u.key !== item.key)
        }, 10000)
        return
      }
      if (task.status === 'failed' || task.status === 'canceled') {
        item.status = 'failed'
        item.error = task.error_msg?.slice(0, 120) || '处理失败'
        await loadDocs()
        return
      }
      setTimeout(tick, 1500)
    } catch {
      item.status = 'failed'
      item.error = '查询任务进度失败'
    }
  }
  setTimeout(tick, 800)
}

async function viewChunks(row: DocumentItem) {
  chunkVisible.value = true
  chunkLoading.value = true
  try {
    const data = await kbApi.chunks(kbId.value, row.id, 30)
    chunkItems.value = data.items
    chunkTotal.value = data.total
  } finally {
    chunkLoading.value = false
  }
}

async function reindex(row: DocumentItem) {
  try {
    await ElMessageBox.confirm(
      '重建会重新解析并向量化该文档，产生少量 embedding 费用。继续吗？',
      '重建向量',
      { type: 'warning' },
    )
  } catch {
    return
  }
  const task = await kbApi.reindex(row.id)
  const item: UploadItem = {
    key: `reindex-${row.id}-${Date.now()}`,
    name: row.name,
    percent: 100,
    status: 'processing',
    taskId: task.id,
  }
  uploads.value.unshift(item)
  pollTask(item)
  ElMessage.info('已提交重建任务')
}

async function removeDoc(row: DocumentItem) {
  try {
    await ElMessageBox.confirm(`确定删除「${row.name}」？原始文件与向量都会删除。`, '删除', {
      type: 'warning',
    })
  } catch {
    return
  }
  await kbApi.removeDocument(row.id)
  ElMessage.success('已删除')
  await Promise.all([loadDocs(), loadKb()])
}

function openSearch() {
  searchVisible.value = true
  searchResult.value = null
}

async function doSearch() {
  if (!searchQuery.value.trim()) return
  searchLoading.value = true
  try {
    searchResult.value = await kbApi.search(kbId.value, searchQuery.value.trim())
  } finally {
    searchLoading.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await loadKb()
    await loadDocs()
  } finally {
    loading.value = false
  }
  // 兜底轮询：处理"刷新页面后仍有文档在排队"的情况
  timer = window.setInterval(() => {
    const busy = docs.value.some((d) =>
      ['pending', 'parsing', 'splitting', 'embedding'].includes(d.status),
    )
    if (busy) loadDocs()
  }, 4000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 10px;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.desc {
  margin-bottom: 14px;
  background: #fff;
  padding: 12px 14px;
  border-radius: 8px;
}

.upload-card {
  border-radius: 10px;
  margin-bottom: 14px;
}

.upload-list {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.upload-item {
  display: flex;
  align-items: center;
  font-size: 12px;
}

.upload-name {
  width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-state {
  width: 110px;
  text-align: right;
  color: #8a919f;
}

.table-card {
  border-radius: 10px;
}

.chunk-card {
  margin-bottom: 10px;
  border-radius: 8px;
}

.chunk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.chunk-idx {
  font-weight: 600;
  color: #3b82f6;
  font-size: 12px;
}

.chunk-body {
  font-size: 13px;
  line-height: 1.7;
  color: #3a4150;
  white-space: pre-wrap;
  word-break: break-word;
}

.search-bar {
  margin-bottom: 12px;
}
</style>
