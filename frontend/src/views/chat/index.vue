<template>
  <div class="portal">
    <!-- 侧边栏 -->
    <Transition name="slide">
      <aside v-if="sidebarOpen" class="sidebar">
        <div class="side-top">
          <div class="brand">
            <span class="brand-mark">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
                <path
                  d="M4 7.5A2.5 2.5 0 016.5 5h4L13 7.5h4.5A2.5 2.5 0 0120 10v7a2.5 2.5 0 01-2.5 2.5h-11A2.5 2.5 0 014 17V7.5z"
                  stroke="currentColor"
                  stroke-width="1.7"
                  stroke-linejoin="round"
                />
              </svg>
            </span>
            <span class="brand-name">知识库</span>
          </div>

          <button class="icon-btn" title="收起侧栏" @click="sidebarOpen = false">
            <svg viewBox="0 0 24 24" width="17" height="17" fill="none">
              <path
                d="M4 6h16M4 12h11M4 18h16"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
              />
            </svg>
          </button>
        </div>

        <button class="new-chat" @click="openNew">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none">
            <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" />
          </svg>
          新对话
        </button>

        <div class="session-scroll">
          <div v-if="sessions.length === 0" class="side-empty">还没有对话</div>

          <template v-for="group in groupedSessions" :key="group.label">
            <div class="group-label">{{ group.label }}</div>
            <button
              v-for="s in group.items"
              :key="s.id"
              class="session"
              :class="{ active: s.id === currentId }"
              @click="selectSession(s.id)"
            >
              <span class="session-text">{{ s.title || '未命名对话' }}</span>
              <span class="session-del" title="删除" @click.stop="removeSession(s.id)">
                <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
                  <path
                    d="M6 7h12M10 7V5.5A1.5 1.5 0 0111.5 4h1A1.5 1.5 0 0114 5.5V7m-6 0l.7 11a1.5 1.5 0 001.5 1.4h3.6a1.5 1.5 0 001.5-1.4L16 7"
                    stroke="currentColor"
                    stroke-width="1.6"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </span>
            </button>
          </template>
        </div>

        <div class="side-foot">
          <Transition name="pop">
            <div v-if="userMenuOpen" class="user-menu" @click.stop>
              <button class="menu-item" @click="openPwd">修改密码</button>
              <button v-if="canAdmin" class="menu-item" @click="goAdmin">管理后台</button>
              <div class="menu-sep" />
              <button class="menu-item danger" @click="doLogout">退出登录</button>
            </div>
          </Transition>

          <div class="user-chip" @click.stop="toggleUserMenu">
            <span class="avatar">{{ (userName || 'U').slice(0, 1) }}</span>
            <span class="user-name">{{ userName }}</span>
            <svg class="chev" :class="{ open: userMenuOpen }" viewBox="0 0 24 24" width="14" height="14" fill="none">
              <path d="M8 10l4 4 4-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
            </svg>
          </div>
        </div>
      </aside>
    </Transition>

    <!-- 主区 -->
    <main class="main">
      <header class="topbar">
        <button v-if="!sidebarOpen" class="icon-btn" title="展开侧栏" @click="sidebarOpen = true">
          <svg viewBox="0 0 24 24" width="17" height="17" fill="none">
            <path d="M4 6h16M4 12h11M4 18h16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
          </svg>
        </button>

        <div class="topbar-title">
          <span class="t-name">{{ currentSession?.title || '新对话' }}</span>
          <span v-if="currentSession?.chat_model" class="t-model">{{ currentSession.chat_model }}</span>
        </div>

        <div class="topbar-right">
          <button v-if="canAdmin" class="ghost-btn" @click="router.push('/admin/dashboard')">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
              <path
                d="M12 15a3 3 0 100-6 3 3 0 000 6z"
                stroke="currentColor"
                stroke-width="1.7"
              />
              <path
                d="M19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 00-1.8-.3 1.6 1.6 0 00-1 1.5V21a2 2 0 11-4 0v-.1A1.6 1.6 0 008.6 19a1.6 1.6 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.6 1.6 0 00.3-1.8 1.6 1.6 0 00-1.5-1H3a2 2 0 110-4h.1A1.6 1.6 0 004.6 8.6a1.6 1.6 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.6 1.6 0 001.8.3H9a1.6 1.6 0 001-1.5V3a2 2 0 114 0v.1a1.6 1.6 0 001 1.5 1.6 1.6 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 00-.3 1.8V9a1.6 1.6 0 001.5 1H21a2 2 0 110 4h-.1a1.6 1.6 0 00-1.5 1z"
                stroke="currentColor"
                stroke-width="1.4"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            管理后台
          </button>

          <button class="avatar-btn" title="账号" @click="openUserMenuFromTop">
            {{ (userName || 'U').slice(0, 1) }}
          </button>
        </div>
      </header>

      <div ref="scrollerRef" class="scroller" @scroll="onScroll">
        <!-- 空状态 -->
        <div v-if="!currentId" class="welcome">
          <div class="welcome-mark">
            <svg viewBox="0 0 24 24" width="26" height="26" fill="none">
              <path
                d="M4 7.5A2.5 2.5 0 016.5 5h4L13 7.5h4.5A2.5 2.5 0 0120 10v7a2.5 2.5 0 01-2.5 2.5h-11A2.5 2.5 0 014 17V7.5z"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linejoin="round"
              />
            </svg>
          </div>
          <h1>今天想了解什么？</h1>
          <p class="welcome-sub">基于你所在的知识库回答，每条结论都会标注来源</p>

          <div class="suggestions">
            <button
              v-for="s in suggestions"
              :key="s"
              class="sug"
              @click="useSuggestion(s)"
            >
              <span>{{ s }}</span>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
                <path
                  d="M7 17L17 7M17 7H9M17 7v8"
                  stroke="currentColor"
                  stroke-width="1.7"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
          </div>

          <button class="welcome-cta" @click="openNew">开始新对话</button>
        </div>

        <!-- 消息流 -->
        <div v-else class="thread">
          <article
            v-for="m in messages"
            :key="m.key"
            class="msg"
            :class="m.role"
          >
            <div v-if="m.role === 'user'" class="bubble-user">{{ m.content }}</div>

            <template v-else>
              <div class="ai-avatar">
                <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
                  <path
                    d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linejoin="round"
                  />
                </svg>
              </div>

              <div class="ai-body">
                <div
                  class="md-body"
                  v-html="m.html"
                  @click="onContentClick($event, m)"
                />
                <span v-if="m.streaming" class="caret" />

                <div v-if="!m.streaming && m.content" class="msg-tools">
                  <button class="tool" :class="{ on: m.feedback === 1 }" title="有帮助" @click="giveFeedback(m, 1)">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
                      <path
                        d="M7 10v9H4V10h3zm0 0l3.5-6a1.5 1.5 0 012.8.8V9h4.2a2 2 0 011.9 2.5l-1.3 5.3A2 2 0 0116.2 18H10a3 3 0 01-3-3"
                        stroke="currentColor"
                        stroke-width="1.6"
                        stroke-linejoin="round"
                      />
                    </svg>
                  </button>
                  <button class="tool" :class="{ bad: m.feedback === -1 }" title="没帮助" @click="giveFeedback(m, -1)">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
                      <path
                        d="M17 14V5h3v9h-3zm0 0l-3.5 6a1.5 1.5 0 01-2.8-.8V15H6.5a2 2 0 01-1.9-2.5l1.3-5.3A2 2 0 017.8 6H14a3 3 0 013 3"
                        stroke="currentColor"
                        stroke-width="1.6"
                        stroke-linejoin="round"
                      />
                    </svg>
                  </button>
                  <button class="tool" title="复制" @click="copyMessage(m)">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
                      <rect x="9" y="9" width="10" height="10" rx="2" stroke="currentColor" stroke-width="1.6" />
                      <path d="M15 6.5A2.5 2.5 0 0012.5 4H7a3 3 0 00-3 3v5.5A2.5 2.5 0 006.5 15" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
                    </svg>
                  </button>

                  <span v-if="m.citations?.length" class="cite-pill" @click="openCitations(m)">
                    {{ m.citations.length }} 条来源
                  </span>
                  <span v-if="m.latency_ms" class="meta">{{ (m.latency_ms / 1000).toFixed(1) }}s</span>
                </div>
              </div>
            </template>
          </article>

          <div v-if="retrieval && sending" class="retrieving">
            <span class="pulse" />
            正在检索知识库…
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="composer-wrap">
        <div class="composer" :class="{ focused, empty: !question.trim() }">
          <textarea
            ref="inputRef"
            v-model="question"
            rows="1"
            :placeholder="currentId ? '输入你的问题…' : '请先新建一个对话'"
            :disabled="!currentId || sending"
            @input="autoGrow"
            @keydown.enter.exact.prevent="send"
            @focus="focused = true"
            @blur="focused = false"
          />

          <div class="composer-bar">
            <div class="kb-chip" :title="kbNames">
              <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
                <path
                  d="M4 7.5A2.5 2.5 0 016.5 5h4L13 7.5h4.5A2.5 2.5 0 0120 10v7a2.5 2.5 0 01-2.5 2.5h-11A2.5 2.5 0 014 17V7.5z"
                  stroke="currentColor"
                  stroke-width="1.7"
                  stroke-linejoin="round"
                />
              </svg>
              {{ kbNames }}
            </div>

            <button v-if="sending" class="send stop" title="停止生成" @click="stop">
              <svg viewBox="0 0 24 24" width="13" height="13">
                <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />
              </svg>
            </button>
            <button
              v-else
              class="send"
              :disabled="!question.trim() || !currentId"
              title="发送"
              @click="send"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none">
                <path
                  d="M12 19V5M12 5l-6 6M12 5l6 6"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
          </div>
        </div>
        <p class="composer-hint">Enter 发送 · Shift + Enter 换行 · 回答可能不准确，请核对来源</p>
      </div>
    </main>

    <!-- 新建对话 -->
    <UiModal v-model:open="newOpen" title="新建对话">
      <div v-if="kbs.length === 0" class="empty-kb">
        <p>当前没有可用的知识库。</p>
        <p class="sub">问答必须基于知识库。请联系管理员授权，或先在后台创建并上传文档。</p>
        <button v-if="canAdmin" class="mini-ghost" @click="goAdminKb">去创建知识库</button>
      </div>

      <template v-else>
        <div class="field">
          <label>选择知识库</label>
          <div class="kb-list">
            <button
              v-for="kb in kbs"
              :key="kb.id"
              class="kb-opt"
              :class="{ on: newKbIds.includes(kb.id) }"
              @click="toggleKb(kb.id)"
            >
              <span class="tick">
                <svg v-if="newKbIds.includes(kb.id)" viewBox="0 0 24 24" width="12" height="12" fill="none">
                  <path d="M5 12.5l4.5 4.5L19 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </span>
              <span class="kb-opt-name">{{ kb.name }}</span>
              <span class="kb-opt-meta">{{ kb.doc_count }} 篇</span>
            </button>
          </div>
        </div>

        <div class="field">
          <label>对话标题 <span class="opt">可选</span></label>
          <input v-model="newTitle" class="text-input" placeholder="默认取第一个问题" maxlength="50" />
        </div>
      </template>

      <template #footer>
        <button class="btn ghost" @click="newOpen = false">取消</button>
        <button class="btn primary" :disabled="!newKbIds.length || creating" @click="createSession">
          {{ creating ? '创建中…' : '开始对话' }}
        </button>
      </template>
    </UiModal>

    <!-- 引用来源 -->
    <UiModal v-model:open="citeOpen" title="引用来源" width="560px">
      <div class="cite-list">
        <div v-for="c in activeCitations" :key="c.chunk_id" class="cite-item">
          <div class="cite-head">
            <span class="cite-idx">{{ c.index }}</span>
            <span class="cite-doc">文档 {{ c.doc_id }}</span>
            <span class="cite-score">相关度 {{ c.score }}</span>
          </div>
          <p class="cite-text">{{ c.snippet }}</p>
        </div>
      </div>
    </UiModal>

    <!-- 修改密码 -->
    <UiModal v-model:open="pwdOpen" title="修改密码">
      <div class="field">
        <label>原密码</label>
        <input v-model="pwd.old" type="password" class="text-input" autocomplete="current-password" />
      </div>
      <div class="field">
        <label>新密码</label>
        <input v-model="pwd.new1" type="password" class="text-input" placeholder="8~64 位，含字母和数字" />
      </div>
      <div class="field">
        <label>确认新密码</label>
        <input v-model="pwd.new2" type="password" class="text-input" />
      </div>
      <template #footer>
        <button class="btn ghost" @click="pwdOpen = false">取消</button>
        <button class="btn primary" :disabled="pwdLoading" @click="submitPwd">
          {{ pwdLoading ? '提交中…' : '确认修改' }}
        </button>
      </template>
    </UiModal>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { authApi } from '@/api/auth'
import { askStream, chatApi, type ChatMessage, type ChatSession, type Citation } from '@/api/chat'
import { kbApi, type KnowledgeBase } from '@/api/kb'
import UiModal from '@/components/ui/UiModal.vue'
import { hasAdminAccess } from '@/router'
import { useUserStore } from '@/stores/user'
import { createRenderScheduler, renderMarkdown } from '@/utils/markdown'
import { notify } from '@/utils/toast'

interface UiMessage extends Partial<ChatMessage> {
  key: string
  role: 'user' | 'assistant'
  content: string
  html?: string
  citations: Citation[]
  streaming?: boolean
  latency_ms?: number
  feedback?: number | null
}

const router = useRouter()
const store = useUserStore()

const sidebarOpen = ref(true)
const userMenuOpen = ref(false)
const focused = ref(false)
const sending = ref(false)

const sessions = ref<ChatSession[]>([])
const currentId = ref<number | null>(null)
const messages = ref<UiMessage[]>([])
const question = ref('')
const kbs = ref<KnowledgeBase[]>([])
const retrieval = ref<{ need_retrieve: boolean; reason: string; hits: unknown[] } | null>(null)

const newOpen = ref(false)
const newKbIds = ref<number[]>([])
const newTitle = ref('')
const creating = ref(false)

const citeOpen = ref(false)
const activeCitations = ref<Citation[]>([])

const pwdOpen = ref(false)
const pwdLoading = ref(false)
const pwd = reactive({ old: '', new1: '', new2: '' })

const scrollerRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLTextAreaElement | null>(null)
let controller: AbortController | null = null
let stickToBottom = true

const userName = computed(() => store.displayName)
const canAdmin = computed(() => hasAdminAccess())
const currentSession = computed(() => sessions.value.find((s) => s.id === currentId.value) || null)

const suggestions = [
  '出差住宿的报销标准是什么？',
  '年假可以结转几天？',
  '数据库备份保留多久？',
  '服务器磁盘告警阈值是多少？',
]

const kbNames = computed(() => {
  const ids = currentSession.value?.kb_ids || []
  const names = ids.map((id) => kbs.value.find((k) => k.id === id)?.name || `库 ${id}`)
  return names.length ? names.join('、') : '未绑定知识库'
})

/** 会话按时间分组，让长列表有层次而不是一条大长串 */
const groupedSessions = computed(() => {
  const buckets: Record<string, ChatSession[]> = {}
  const now = new Date()
  const yesterday = new Date(now.getTime() - 86400000)

  for (const s of sessions.value) {
    const d = new Date(s.updated_at)
    let label = '更早'
    if (d.toDateString() === now.toDateString()) label = '今天'
    else if (d.toDateString() === yesterday.toDateString()) label = '昨天'
    else if (now.getTime() - d.getTime() < 7 * 86400000) label = '近 7 天'
    ;(buckets[label] ||= []).push(s)
  }

  const order = ['今天', '昨天', '近 7 天', '更早']
  return order
    .filter((k) => buckets[k]?.length)
    .map((label) => ({ label, items: buckets[label] }))
})

const scheduleRender = createRenderScheduler(60)

function refreshHtml(m: UiMessage) {
  m.html = renderMarkdown(m.content, (m.citations || []).map((c) => c.index))
}

function toUi(m: ChatMessage): UiMessage {
  const item: UiMessage = { ...m, key: `m-${m.id}`, citations: m.citations || [] }
  item.html = renderMarkdown(item.content, item.citations.map((c) => c.index))
  return item
}

function onScroll() {
  const el = scrollerRef.value
  if (!el) return
  // 用户主动上滑查看历史时，不要强行拽回底部
  stickToBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
}

function scrollToBottom(force = false) {
  if (!force && !stickToBottom) return
  nextTick(() => {
    const el = scrollerRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function autoGrow() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

function onContentClick(ev: MouseEvent, m: UiMessage) {
  const el = ev.target as HTMLElement
  if (!el.classList.contains('cite')) return
  const idx = Number(el.dataset.idx)
  const cite = m.citations?.find((c) => c.index === idx)
  if (cite) {
    activeCitations.value = [cite]
    citeOpen.value = true
  }
}

async function loadSessions() {
  sessions.value = await chatApi.sessions()
}

async function selectSession(id: number) {
  currentId.value = id
  retrieval.value = null
  const rows = await chatApi.messages(id)
  messages.value = rows.map(toUi)
  stickToBottom = true
  scrollToBottom(true)
}

function toggleKb(id: number) {
  const i = newKbIds.value.indexOf(id)
  if (i >= 0) newKbIds.value.splice(i, 1)
  else newKbIds.value.push(id)
}

function openNew() {
  const last = sessions.value[0]
  if (last?.kb_ids?.length) newKbIds.value = [...last.kb_ids]
  else if (kbs.value.length === 1) newKbIds.value = [kbs.value[0].id]
  else newKbIds.value = []

  newTitle.value = ''
  newOpen.value = true
}

async function createSession() {
  if (!newKbIds.value.length) return
  creating.value = true
  try {
    const s = await chatApi.createSession(newKbIds.value, newTitle.value || undefined)
    newOpen.value = false
    await loadSessions()
    await selectSession(s.id)
    notify.success('对话已创建')
    nextTick(() => inputRef.value?.focus())
  } catch (e) {
    notify.error((e as Error).message || '创建失败')
  } finally {
    creating.value = false
  }
}

async function removeSession(id: number) {
  try {
    await chatApi.removeSession(id)
  } catch (e) {
    notify.error((e as Error).message || '删除失败')
    return
  }
  if (currentId.value === id) {
    currentId.value = null
    messages.value = []
  }
  await loadSessions()
  notify.success('已删除对话')
}

function useSuggestion(text: string) {
  if (!currentId.value) {
    newKbIds.value =
      kbs.value.length === 1 ? [kbs.value[0].id] : (sessions.value[0]?.kb_ids ?? [])
    newTitle.value = text.slice(0, 30)
    question.value = text
    newOpen.value = true
    return
  }
  question.value = text
  nextTick(() => {
    inputRef.value?.focus()
    autoGrow()
  })
}

async function send() {
  const q = question.value.trim()
  if (!q || !currentId.value || sending.value) return

  question.value = ''
  nextTick(autoGrow)
  sending.value = true
  retrieval.value = null
  stickToBottom = true

  const userMsg: UiMessage = {
    key: `u-${Date.now()}`,
    role: 'user',
    content: q,
    citations: [],
  }
  const aiMsg = reactive<UiMessage>({
    key: `a-${Date.now()}`,
    role: 'assistant',
    content: '',
    html: '',
    citations: [],
    streaming: true,
  })
  messages.value.push(userMsg, aiMsg)
  scrollToBottom(true)

  controller = new AbortController()

  try {
    await askStream(
      currentId.value,
      q,
      (evt) => {
        if (evt.type === 'retrieval') {
          retrieval.value = evt.data as never
        } else if (evt.type === 'delta') {
          aiMsg.content += evt.data.text
          scheduleRender(() => {
            aiMsg.html = renderMarkdown(aiMsg.content)
          })
          scrollToBottom()
        } else if (evt.type === 'done') {
          aiMsg.citations = evt.data.citations || []
          aiMsg.model = evt.data.model
          aiMsg.latency_ms = evt.data.latency_ms
          aiMsg.feedback = null
          refreshHtml(aiMsg)
        } else if (evt.type === 'error') {
          notify.error(evt.data.message)
          if (!aiMsg.content) aiMsg.content = '生成失败，请重试'
          refreshHtml(aiMsg)
        }
      },
      controller.signal,
    )
  } catch (e) {
    if ((e as Error).name !== 'AbortError') {
      notify.error((e as Error).message || '请求失败')
    }
    if (!aiMsg.content) {
      aiMsg.content = '已停止生成'
      refreshHtml(aiMsg)
    }
  } finally {
    aiMsg.streaming = false
    sending.value = false
    controller = null
    await loadSessions()
    if (currentId.value) {
      const rows = await chatApi.messages(currentId.value)
      messages.value = rows.map(toUi)
      scrollToBottom()
    }
  }
}

function stop() {
  controller?.abort()
}

async function giveFeedback(m: UiMessage, value: number) {
  if (!m.id) return
  const next = m.feedback === value ? null : value
  try {
    await chatApi.feedback(m.id, next)
    m.feedback = next
    notify.success(next === null ? '已取消评价' : '感谢反馈')
  } catch (e) {
    notify.error((e as Error).message || '操作失败')
  }
}

async function copyMessage(m: UiMessage) {
  try {
    await navigator.clipboard.writeText(m.content)
    notify.success('已复制')
  } catch {
    notify.error('复制失败，请手动选择')
  }
}

function openCitations(m: UiMessage) {
  activeCitations.value = m.citations || []
  citeOpen.value = true
}

function toggleUserMenu() {
  userMenuOpen.value = !userMenuOpen.value
}

/** 侧栏收起时，顶栏头像也能打开账号菜单：先把侧栏展开，菜单就在它底部 */
function openUserMenuFromTop() {
  if (!sidebarOpen.value) {
    sidebarOpen.value = true
    userMenuOpen.value = true
    return
  }
  userMenuOpen.value = !userMenuOpen.value
}

function openPwd() {
  userMenuOpen.value = false
  pwd.old = ''
  pwd.new1 = ''
  pwd.new2 = ''
  pwdOpen.value = true
}

async function submitPwd() {
  if (!pwd.old || !pwd.new1) {
    notify.error('请填写完整')
    return
  }
  if (pwd.new1 !== pwd.new2) {
    notify.error('两次输入的新密码不一致')
    return
  }
  pwdLoading.value = true
  try {
    await authApi.changePassword(pwd.old, pwd.new1)
    notify.success('密码已修改，请重新登录')
    pwdOpen.value = false
    await store.logout()
    router.push('/login')
  } catch (e) {
    notify.error((e as Error).message || '修改失败')
  } finally {
    pwdLoading.value = false
  }
}

async function doLogout() {
  userMenuOpen.value = false
  await store.logout()
  router.push('/login')
}

function goAdmin() {
  userMenuOpen.value = false
  router.push('/admin/dashboard')
}

function goAdminKb() {
  newOpen.value = false
  router.push('/admin/kb')
}

function onDocClick() {
  userMenuOpen.value = false
}

onMounted(async () => {
  document.addEventListener('click', onDocClick)
  await loadSessions()
  kbs.value = await kbApi.list()
  if (sessions.value.length) await selectSession(sessions.value[0].id)
  if (window.innerWidth < 900) sidebarOpen.value = false
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
})
</script>

<style scoped>
/* ---------------- 设计变量 ---------------- */
.portal {
  --ink: #17181a;
  --ink-2: #5b6068;
  --ink-3: #9aa0a6;
  --paper: #f7f6f3;
  --surface: #ffffff;
  --line: #ebe9e4;
  --line-2: #f2f0ec;
  --accent: #2f6b57;
  --accent-2: #3d8a6e;
  --accent-soft: #e9f1ed;
  --shadow-1: 0 1px 2px rgba(23, 24, 26, 0.04), 0 2px 8px rgba(23, 24, 26, 0.04);
  --shadow-2: 0 2px 6px rgba(23, 24, 26, 0.05), 0 12px 28px rgba(23, 24, 26, 0.07);
  --shadow-3: 0 4px 12px rgba(23, 24, 26, 0.07), 0 20px 48px rgba(23, 24, 26, 0.1);

  display: flex;
  height: 100%;
  background: var(--paper);
  color: var(--ink);
  font-size: 14px;
  -webkit-font-smoothing: antialiased;
}

/* ---------------- 侧边栏 ---------------- */
.sidebar {
  width: 268px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #fbfaf8;
  border-right: 1px solid var(--line);
}

.side-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 14px 10px 16px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 9px;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  color: #fff;
  background: linear-gradient(160deg, var(--accent-2), var(--accent));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 1px 2px rgba(47, 107, 87, 0.3);
}

.brand-name {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.2px;
}

.icon-btn {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: var(--ink-2);
  cursor: pointer;
  transition:
    background 0.16s ease,
    color 0.16s ease;
}

.icon-btn:hover {
  background: #f0eeea;
  color: var(--ink);
}

.new-chat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  margin: 4px 12px 12px;
  padding: 10px 14px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(165deg, var(--accent-2), var(--accent));
  color: #fff;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.2),
    0 1px 2px rgba(47, 107, 87, 0.28),
    0 6px 16px rgba(47, 107, 87, 0.24);
  transition:
    transform 0.14s ease,
    box-shadow 0.14s ease;
}

.new-chat:hover {
  transform: translateY(-1px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.24),
    0 2px 4px rgba(47, 107, 87, 0.3),
    0 10px 22px rgba(47, 107, 87, 0.28);
}

.new-chat:active {
  transform: translateY(0);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.16);
}

.session-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px 8px;
}

.side-empty {
  padding: 24px 12px;
  text-align: center;
  color: var(--ink-3);
  font-size: 12.5px;
}

.group-label {
  padding: 12px 10px 6px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.6px;
  color: var(--ink-3);
  text-transform: uppercase;
}

.session {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 9px 10px;
  margin-bottom: 2px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--ink-2);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}

.session:hover {
  background: #f1efeb;
  color: var(--ink);
}

.session.active {
  background: #fff;
  color: var(--ink);
  box-shadow: var(--shadow-1);
}

.session.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  width: 3px;
  height: 16px;
  border-radius: 0 3px 3px 0;
  background: var(--accent);
  transform: translateY(-50%);
}

.session-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-del {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  color: var(--ink-3);
  opacity: 0;
  transition:
    opacity 0.15s ease,
    background 0.15s ease,
    color 0.15s ease;
}

.session:hover .session-del {
  opacity: 1;
}

.session-del:hover {
  background: #fdeaea;
  color: #d9534f;
}

.side-foot {
  position: relative;
  padding: 10px;
  border-top: 1px solid var(--line-2);
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 10px;
  border-radius: 12px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.user-chip:hover {
  background: #f1efeb;
}

.avatar {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(160deg, #4a4f57, #2a2d33);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.18);
}

.user-name {
  flex: 1;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chev {
  color: var(--ink-3);
  transition: transform 0.18s ease;
}

.chev.open {
  transform: rotate(180deg);
}

/* 侧栏滑入 */
.slide-enter-active,
.slide-leave-active {
  transition:
    transform 0.26s cubic-bezier(0.2, 0.8, 0.2, 1),
    opacity 0.26s ease;
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(-16px);
  opacity: 0;
}

/* ---------------- 主区 ---------------- */
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  position: relative;
}

.topbar {
  height: 54px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  border-bottom: 1px solid transparent;
  background: linear-gradient(to bottom, rgba(247, 246, 243, 0.96), rgba(247, 246, 243, 0.82));
  backdrop-filter: blur(8px);
}

.topbar-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.t-name {
  font-size: 14px;
  font-weight: 550;
  letter-spacing: -0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 42vw;
}

.t-model {
  font-size: 11.5px;
  color: var(--ink-3);
  padding: 2px 7px;
  border-radius: 6px;
  background: #efece7;
}

.topbar-right {
  margin-left: auto;
}

.ghost-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #fff;
  color: var(--ink-2);
  font-size: 12.5px;
  cursor: pointer;
  box-shadow: 0 1px 1px rgba(23, 24, 26, 0.03);
  transition:
    transform 0.14s ease,
    color 0.14s ease,
    border-color 0.14s ease,
    box-shadow 0.14s ease;
}

.ghost-btn:hover {
  transform: translateY(-1px);
  color: var(--accent);
  border-color: #d5e2db;
  box-shadow: var(--shadow-1);
}

.avatar-btn {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  margin-left: 10px;
  border: none;
  border-radius: 50%;
  background: linear-gradient(160deg, #4a4f57, #2a2d33);
  color: #fff;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.18),
    0 1px 2px rgba(23, 24, 26, 0.16);
  transition: transform 0.14s ease;
}

.avatar-btn:hover {
  transform: translateY(-1px);
}

/* ---------------- 滚动区 ---------------- */
.scroller {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  scroll-behavior: smooth;
}

.welcome {
  max-width: 680px;
  margin: 0 auto;
  padding: 9vh 24px 40px;
  text-align: center;
  animation: rise 0.5s cubic-bezier(0.2, 0.8, 0.2, 1) both;
}

.welcome-mark {
  display: inline-grid;
  place-items: center;
  width: 54px;
  height: 54px;
  margin-bottom: 20px;
  border-radius: 16px;
  color: var(--accent);
  background: linear-gradient(160deg, #fff, #eef4f1);
  box-shadow:
    inset 0 1px 0 #fff,
    0 1px 2px rgba(23, 24, 26, 0.05),
    0 12px 28px rgba(23, 24, 26, 0.07);
}

.welcome h1 {
  margin: 0 0 8px;
  font-size: 27px;
  font-weight: 600;
  letter-spacing: -0.025em;
}

.welcome-sub {
  margin: 0 0 30px;
  font-size: 13.5px;
  color: var(--ink-2);
}

.suggestions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 22px;
}

.sug {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 15px;
  border: 1px solid var(--line);
  border-radius: 13px;
  background: #fff;
  color: var(--ink-2);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  box-shadow: 0 1px 1px rgba(23, 24, 26, 0.03);
  transition:
    transform 0.16s cubic-bezier(0.2, 0.8, 0.2, 1),
    box-shadow 0.16s ease,
    border-color 0.16s ease,
    color 0.16s ease;
}

.sug:hover {
  transform: translateY(-2px);
  color: var(--ink);
  border-color: #dcd9d2;
  box-shadow: var(--shadow-2);
}

.sug svg {
  flex-shrink: 0;
  color: var(--ink-3);
  transition:
    transform 0.18s ease,
    color 0.18s ease;
}

.sug:hover svg {
  transform: translate(2px, -2px);
  color: var(--accent);
}

.welcome-cta {
  padding: 10px 22px;
  border: none;
  border-radius: 11px;
  background: var(--ink);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(23, 24, 26, 0.2), 0 8px 20px rgba(23, 24, 26, 0.14);
  transition:
    transform 0.14s ease,
    box-shadow 0.14s ease;
}

.welcome-cta:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(23, 24, 26, 0.22), 0 12px 26px rgba(23, 24, 26, 0.18);
}

.thread {
  max-width: 740px;
  margin: 0 auto;
  padding: 26px 24px 40px;
}

.msg {
  display: flex;
  gap: 12px;
  margin-bottom: 26px;
  animation: rise 0.32s cubic-bezier(0.2, 0.8, 0.2, 1) both;
}

.msg.user {
  justify-content: flex-end;
}

.bubble-user {
  max-width: 74%;
  padding: 11px 16px;
  border-radius: 18px 18px 4px 18px;
  background: linear-gradient(165deg, #26282d, #17181a);
  color: #f7f6f3;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 1px 2px rgba(23, 24, 26, 0.16),
    0 8px 20px rgba(23, 24, 26, 0.14);
}

.ai-avatar {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  margin-top: 2px;
  border-radius: 9px;
  color: var(--accent);
  background: linear-gradient(160deg, #fff, #eaf1ee);
  box-shadow:
    inset 0 1px 0 #fff,
    0 1px 2px rgba(23, 24, 26, 0.06);
}

.ai-body {
  flex: 1;
  min-width: 0;
  padding-top: 1px;
}

/* ---------------- Markdown 正文 ---------------- */
.md-body {
  font-size: 14.5px;
  line-height: 1.78;
  color: #23252a;
  word-break: break-word;
}

.md-body :deep(p) {
  margin: 0 0 12px;
}

.md-body :deep(p:last-child) {
  margin-bottom: 0;
}

.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  margin: 20px 0 10px;
  font-weight: 600;
  letter-spacing: -0.015em;
  line-height: 1.42;
}

.md-body :deep(h1) {
  font-size: 19px;
}
.md-body :deep(h2) {
  font-size: 17px;
}
.md-body :deep(h3) {
  font-size: 15.5px;
}
.md-body :deep(h4) {
  font-size: 14.5px;
}

.md-body :deep(h1:first-child),
.md-body :deep(h2:first-child),
.md-body :deep(h3:first-child) {
  margin-top: 0;
}

.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 8px 0 12px;
  padding-left: 22px;
}

.md-body :deep(li) {
  margin: 4px 0;
}

.md-body :deep(li::marker) {
  color: var(--ink-3);
}

.md-body :deep(strong) {
  font-weight: 600;
  color: #101114;
}

.md-body :deep(code) {
  padding: 1.5px 6px;
  margin: 0 1px;
  border-radius: 5px;
  background: #f0eeea;
  font-family: 'SF Mono', Consolas, Monaco, monospace;
  font-size: 12.8px;
  color: #8a4b2f;
}

.md-body :deep(pre) {
  margin: 12px 0;
  padding: 14px 16px;
  border-radius: 12px;
  background: #1d1f23;
  overflow-x: auto;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.md-body :deep(pre code) {
  padding: 0;
  background: none;
  color: #e6e6e3;
  font-size: 12.8px;
  line-height: 1.65;
}

.md-body :deep(table) {
  display: block;
  overflow-x: auto;
  margin: 12px 0;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 13px;
  border: 1px solid var(--line);
  border-radius: 10px;
}

.md-body :deep(th),
.md-body :deep(td) {
  padding: 8px 13px;
  text-align: left;
  border-bottom: 1px solid var(--line-2);
}

.md-body :deep(tr:last-child td) {
  border-bottom: none;
}

.md-body :deep(th) {
  background: #faf9f7;
  font-weight: 600;
  color: var(--ink);
}

.md-body :deep(blockquote) {
  margin: 12px 0;
  padding: 2px 0 2px 14px;
  border-left: 3px solid #ded9d0;
  color: var(--ink-2);
}

.md-body :deep(a) {
  color: var(--accent);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.md-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--line);
  margin: 18px 0;
}

/* 引用角标 */
.md-body :deep(.cite) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 17px;
  height: 17px;
  padding: 0 4px;
  margin: 0 2px;
  border-radius: 5px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 600;
  vertical-align: 1px;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease,
    transform 0.15s ease;
}

.md-body :deep(.cite:hover) {
  background: var(--accent);
  color: #fff;
  transform: scale(1.08);
}

/* 流式光标 */
.caret {
  display: inline-block;
  width: 7px;
  height: 15px;
  margin-left: 2px;
  border-radius: 2px;
  background: var(--accent);
  vertical-align: -2px;
  animation: blink 1.05s steps(2, start) infinite;
}

.msg-tools {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 10px;
  opacity: 0;
  transition: opacity 0.18s ease;
}

.msg:hover .msg-tools,
.msg-tools:focus-within {
  opacity: 1;
}

.tool {
  display: grid;
  place-items: center;
  width: 27px;
  height: 27px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}

.tool:hover {
  background: #efede9;
  color: var(--ink);
}

.tool.on {
  color: var(--accent);
  background: var(--accent-soft);
}

.tool.bad {
  color: #d9534f;
  background: #fdeaea;
}

.cite-pill {
  margin-left: 6px;
  padding: 4px 9px;
  border-radius: 7px;
  background: #f2f0ec;
  color: var(--ink-2);
  font-size: 11.5px;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}

.cite-pill:hover {
  background: var(--accent-soft);
  color: var(--accent);
}

.meta {
  margin-left: 6px;
  font-size: 11.5px;
  color: var(--ink-3);
}

.retrieving {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 38px;
  font-size: 12.5px;
  color: var(--ink-3);
  animation: rise 0.3s ease both;
}

.pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.3s ease-in-out infinite;
}

/* ---------------- 输入区 ---------------- */
.composer-wrap {
  flex-shrink: 0;
  padding: 0 24px 18px;
  background: linear-gradient(to top, var(--paper) 62%, rgba(247, 246, 243, 0));
}

.composer {
  max-width: 740px;
  margin: 0 auto;
  padding: 12px 12px 10px 16px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: #fff;
  box-shadow:
    0 1px 2px rgba(23, 24, 26, 0.04),
    0 8px 24px rgba(23, 24, 26, 0.06);
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.composer.focused {
  border-color: #cddfd6;
  box-shadow:
    0 0 0 3px rgba(47, 107, 87, 0.09),
    0 10px 28px rgba(23, 24, 26, 0.08);
}

.composer textarea {
  display: block;
  width: 100%;
  max-height: 160px;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  color: var(--ink);
  font-family: inherit;
  font-size: 14.5px;
  line-height: 1.65;
  padding: 2px 0 6px;
}

.composer textarea::placeholder {
  color: var(--ink-3);
}

.composer-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.kb-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: 60%;
  padding: 5px 10px;
  border-radius: 8px;
  background: #f5f3ef;
  color: var(--ink-2);
  font-size: 11.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.send {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(165deg, var(--accent-2), var(--accent));
  color: #fff;
  cursor: pointer;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 1px 2px rgba(47, 107, 87, 0.3),
    0 6px 14px rgba(47, 107, 87, 0.22);
  transition:
    transform 0.14s ease,
    box-shadow 0.14s ease,
    opacity 0.14s ease;
}

.send:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.26),
    0 2px 4px rgba(47, 107, 87, 0.32),
    0 10px 20px rgba(47, 107, 87, 0.26);
}

.send:active:not(:disabled) {
  transform: translateY(0) scale(0.96);
}

.send:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  box-shadow: none;
}

.send.stop {
  background: linear-gradient(165deg, #4a4f57, #2a2d33);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.14),
    0 1px 2px rgba(23, 24, 26, 0.2);
}

.composer-hint {
  max-width: 740px;
  margin: 9px auto 0;
  text-align: center;
  font-size: 11px;
  color: var(--ink-3);
}

/* ---------------- 用户菜单 ---------------- */
.user-menu {
  position: absolute;
  left: 10px;
  bottom: calc(100% + 2px);
  z-index: 1500;
  width: 182px;
  padding: 6px;
  border: 1px solid var(--line);
  border-radius: 13px;
  background: #fff;
  box-shadow: var(--shadow-3);
}

.menu-item {
  display: block;
  width: 100%;
  padding: 9px 11px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--ink-2);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.14s ease,
    color 0.14s ease;
}

.menu-item:hover {
  background: #f5f3ef;
  color: var(--ink);
}

.menu-item.danger:hover {
  background: #fdeaea;
  color: #d9534f;
}

.menu-sep {
  height: 1px;
  margin: 5px 8px;
  background: var(--line-2);
}

.pop-enter-active {
  transition:
    opacity 0.16s ease,
    transform 0.16s cubic-bezier(0.2, 0.8, 0.2, 1);
}

.pop-leave-active {
  transition:
    opacity 0.12s ease,
    transform 0.12s ease;
}

.pop-enter-from,
.pop-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.97);
}

/* ---------------- 弹窗内部 ---------------- */
.field {
  margin-bottom: 16px;
}

.field label {
  display: block;
  margin-bottom: 7px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--ink-2);
}

.field label .opt {
  font-weight: 400;
  color: var(--ink-3);
}

.text-input {
  width: 100%;
  padding: 10px 13px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: #fbfaf8;
  color: var(--ink);
  font-family: inherit;
  font-size: 13.5px;
  outline: none;
  transition:
    border-color 0.16s ease,
    background 0.16s ease,
    box-shadow 0.16s ease;
}

.text-input:focus {
  background: #fff;
  border-color: #cddfd6;
  box-shadow: 0 0 0 3px rgba(47, 107, 87, 0.09);
}

.kb-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  max-height: 260px;
  overflow-y: auto;
}

.kb-opt {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: #fff;
  color: var(--ink-2);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background 0.15s ease,
    color 0.15s ease;
}

.kb-opt:hover {
  border-color: #dcd9d2;
  color: var(--ink);
}

.kb-opt.on {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.tick {
  display: grid;
  place-items: center;
  width: 17px;
  height: 17px;
  flex-shrink: 0;
  border: 1.5px solid #d5d2cb;
  border-radius: 5px;
  background: #fff;
  color: #fff;
  transition:
    background 0.15s ease,
    border-color 0.15s ease;
}

.kb-opt.on .tick {
  border-color: var(--accent);
  background: var(--accent);
}

.kb-opt-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-opt-meta {
  font-size: 11.5px;
  color: var(--ink-3);
}

.empty-kb {
  padding: 6px 0 10px;
}

.empty-kb p {
  margin: 0 0 8px;
  font-size: 13.5px;
  color: var(--ink);
}

.empty-kb .sub {
  font-size: 12.5px;
  color: var(--ink-2);
  line-height: 1.7;
}

.mini-ghost {
  margin-top: 8px;
  padding: 7px 13px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #fff;
  color: var(--accent);
  font-size: 12.5px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.mini-ghost:hover {
  background: var(--accent-soft);
}

.btn {
  padding: 9px 17px;
  border: none;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition:
    transform 0.14s ease,
    box-shadow 0.14s ease,
    opacity 0.14s ease;
}

.btn.ghost {
  background: #f5f3ef;
  color: var(--ink-2);
}

.btn.ghost:hover {
  background: #edeae4;
  color: var(--ink);
}

.btn.primary {
  background: linear-gradient(165deg, var(--accent-2), var(--accent));
  color: #fff;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.2),
    0 1px 2px rgba(47, 107, 87, 0.28);
}

.btn.primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.24),
    0 2px 4px rgba(47, 107, 87, 0.3),
    0 8px 18px rgba(47, 107, 87, 0.22);
}

.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.cite-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-bottom: 8px;
}

.cite-item {
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #fbfaf8;
}

.cite-head {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 7px;
}

.cite-idx {
  display: grid;
  place-items: center;
  width: 19px;
  height: 19px;
  border-radius: 6px;
  background: var(--accent);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
}

.cite-doc {
  font-size: 12px;
  color: var(--ink-2);
}

.cite-score {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--ink-3);
}

.cite-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.75;
  color: #3a3d42;
  white-space: pre-wrap;
}

/* ---------------- 动画 ---------------- */
@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@keyframes blink {
  to {
    visibility: hidden;
  }
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(0.85);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}

@media (max-width: 860px) {
  .sidebar {
    position: absolute;
    z-index: 1200;
    height: 100%;
    box-shadow: var(--shadow-3);
  }

  .suggestions {
    grid-template-columns: 1fr;
  }

  .welcome {
    padding-top: 6vh;
  }

  .thread,
  .composer {
    padding-left: 16px;
    padding-right: 16px;
  }

  .t-name {
    max-width: 50vw;
  }
}
</style>
