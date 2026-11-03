<template>
  <div>
    <div class="head">
      <div class="head-left">
        <div class="head-icon">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none">
            <path
              d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3zM18.5 14l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z"
              fill="currentColor"
            />
          </svg>
        </div>
        <div>
          <h2>智能体</h2>
          <p class="sub">
            把模型、知识库、提示词、检索参数封装成可发布的整体。前台用户只能选用，不能改配置。
          </p>
        </div>
      </div>
      <button class="btn btn-primary" @click="openCreate">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
          <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
        </svg>
        新建智能体
      </button>
    </div>

    <el-empty v-if="!loading && !list.length" description="还没有智能体，点右上角新建一个" />

    <div class="grid">
      <article v-for="a in list" :key="a.id" class="card">
        <header class="card-top">
          <span class="emoji-badge">{{ a.emoji }}</span>
          <div class="title">
            <strong>{{ a.name }}</strong>
            <div class="tags">
              <span class="chip" :class="a.is_published ? 'chip-live' : 'chip-draft'">
                <i class="dot" />{{ a.is_published ? '已发布' : '草稿' }}
              </span>
              <span v-if="!a.is_public" class="chip chip-private">
                <i class="dot" />非公开
              </span>
            </div>
          </div>
        </header>

        <p class="desc">{{ a.description || '暂无描述，可在编辑中补充' }}</p>

        <ul class="meta">
          <li>
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
              <path d="M4 7.5A2.5 2.5 0 016.5 5h4L13 7.5h4.5A2.5 2.5 0 0120 10v7a2.5 2.5 0 01-2.5 2.5h-11A2.5 2.5 0 014 17V7.5z" stroke="currentColor" stroke-width="1.7" />
            </svg>
            <span class="text-ellipsis">{{ a.kb_names.length ? a.kb_names.join('、') : '未绑定知识库' }}</span>
          </li>
          <li>
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
              <rect x="4" y="6" width="16" height="12" rx="3" stroke="currentColor" stroke-width="1.7" />
              <circle cx="9" cy="12" r="1.4" fill="currentColor" />
              <circle cx="15" cy="12" r="1.4" fill="currentColor" />
            </svg>
            <span>{{ a.model || '跟随全局默认' }}</span>
          </li>
          <li>
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
              <path d="M5 18l-1 4 4-1h9.5A2.5 2.5 0 0020 18.5v-11A2.5 2.5 0 0017.5 5h-11A2.5 2.5 0 004 7.5V18z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" />
            </svg>
            <span>{{ a.session_count }} 会话 · {{ a.message_count }} 消息</span>
          </li>
        </ul>

        <footer class="ops">
          <button class="btn btn-ghost" @click="openTest(a)">试跑</button>
          <button class="btn btn-ghost" @click="openEdit(a)">编辑</button>
          <button
            class="btn"
            :class="a.is_published ? 'btn-ghost' : 'btn-primary'"
            @click="togglePublish(a)"
          >
            {{ a.is_published ? '下线' : '发布' }}
          </button>
          <button class="btn btn-soft-danger" @click="remove(a)">删除</button>
        </footer>
      </article>
    </div>

    <!-- 创建/编辑 -->
    <el-drawer v-model="editorVisible" :title="editingId ? '编辑智能体' : '新建智能体'" size="640px">
      <el-form label-width="88px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="96" placeholder="如：HR 政策助手" />
        </el-form-item>
        <el-form-item label="图标">
          <el-input v-model="form.emoji" maxlength="8" style="width: 100px" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="给前台用户看的一句话介绍" />
        </el-form-item>
        <el-form-item label="知识库" required>
          <el-select v-model="form.kb_ids" multiple filterable style="width: 100%">
            <el-option v-for="kb in kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
          <div class="hint">用户能通过此智能体检索这些库，即使他们不是库成员</div>
        </el-form-item>
        <el-form-item label="对话模型">
          <el-select v-model="form.provider" clearable placeholder="跟随全局默认" style="width: 100%">
            <el-option
              v-for="m in models"
              :key="m.id"
              :label="`${m.name}（${m.provider}/${m.model}）`"
              :value="m.provider"
            />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">提示词覆盖（留空使用全局）</el-divider>
        <el-form-item
          v-for="key in PROMPT_KEYS"
          :key="key"
          :label="PROMPT_LABELS[key]"
        >
          <el-input
            v-model="form.prompt_overrides[key]"
            type="textarea"
            :rows="4"
            :placeholder="`留空使用全局 ${key} 模板。变量：{{context}} {{question}} {{kb_name}}`"
          />
        </el-form-item>

        <el-divider content-position="left">检索参数（可选覆盖）</el-divider>
        <el-form-item label="召回条数">
          <el-input-number v-model="retrieveCfg.top_k" :min="1" :max="100" />
          <span class="hint" style="margin-left: 8px">留空用知识库配置</span>
        </el-form-item>
        <el-form-item label="精排保留">
          <el-input-number v-model="retrieveCfg.rerank_top_n" :min="1" :max="30" />
        </el-form-item>

        <el-divider content-position="left">发布</el-divider>
        <el-form-item label="发布状态">
          <el-switch v-model="form.is_published" active-text="已发布" inactive-text="草稿" />
        </el-form-item>
        <el-form-item label="全员可用">
          <el-switch v-model="form.is_public" />
          <span class="hint" style="margin-left: 8px">关闭后仅管理员可用（按人授权在二期）</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-drawer>

    <!-- 试跑 -->
    <el-dialog v-model="testVisible" :title="`试跑：${testing?.name ?? ''}`" width="720px">
      <el-input v-model="testQuestion" placeholder="输入测试问题，如：v-for 的 key 怎么选">
        <template #append>
          <el-button :loading="testing" @click="runTest">运行</el-button>
        </template>
      </el-input>
      <el-alert
        v-if="testResult"
        type="info"
        :closable="false"
        show-icon
        style="margin-top: 12px"
        :title="`${testResult.model} · ${testResult.latency_ms}ms · ${testResult.prompt_tokens}+${testResult.completion_tokens} token · 命中 ${testResult.sources} 条`"
      />
      <pre v-if="testResult" class="test-out">{{ testResult.answer }}</pre>
      <div v-if="testResult?.citations?.length" class="cites">
        <div class="cite-title">引用</div>
        <div v-for="cite in testResult.citations" :key="cite.index" class="cite-item">
          [{{ cite.index }}] {{ cite.snippet }}
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { agentApi, type AgentItem, type AgentTestResult } from '@/api/agents'
import { kbApi, type KnowledgeBase } from '@/api/kb'
import { adminApi, type ModelConfigItem } from '@/api/admin'

const PROMPT_KEYS = ['system_qa', 'direct_answer', 'query_rewrite'] as const
const PROMPT_LABELS: Record<string, string> = {
  system_qa: '知识库问答',
  direct_answer: '寒暄回复',
  query_rewrite: '查询改写',
}

const list = ref<AgentItem[]>([])
const kbs = ref<KnowledgeBase[]>([])
const models = ref<ModelConfigItem[]>([])
const loading = ref(false)
const saving = ref(false)

const editorVisible = ref(false)
const editingId = ref<number | null>(null)

const testVisible = ref(false)
const testing = ref<AgentItem | null>(null)
const testQuestion = ref('')
const testResult = ref<AgentTestResult | null>(null)
const testRunning = ref(false)

const form = reactive({
  name: '',
  description: '' as string | null,
  emoji: '🤖',
  kb_ids: [] as number[],
  provider: null as string | null,
  prompt_overrides: {} as Record<string, string>,
  is_published: false,
  is_public: true,
})
const retrieveCfg = reactive({ top_k: 30, rerank_top_n: 8 })

async function load() {
  loading.value = true
  try {
    list.value = await agentApi.adminList()
  } finally {
    loading.value = false
  }
}

async function loadRefs() {
  if (!kbs.value.length) {
    kbs.value = await kbApi.list().catch(() => [])
  }
  if (!models.value.length) {
    models.value = await adminApi.models().catch(() => [])
  }
}

function resetForm() {
  form.name = ''
  form.description = ''
  form.emoji = '🤖'
  form.kb_ids = []
  form.provider = null
  form.prompt_overrides = {}
  form.is_published = false
  form.is_public = true
  retrieveCfg.top_k = 30
  retrieveCfg.rerank_top_n = 8
}

async function openCreate() {
  editingId.value = null
  resetForm()
  await loadRefs()
  editorVisible.value = true
}

async function openEdit(a: AgentItem) {
  editingId.value = a.id
  await loadRefs()
  form.name = a.name
  form.description = a.description ?? ''
  form.emoji = a.emoji
  form.kb_ids = [...a.kb_ids]
  form.provider = a.provider
  form.prompt_overrides = { ...a.prompt_overrides }
  form.is_published = a.is_published
  form.is_public = a.is_public
  retrieveCfg.top_k = Number(a.retrieve_config?.top_k ?? 30)
  retrieveCfg.rerank_top_n = Number(a.retrieve_config?.rerank_top_n ?? 8)
  editorVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  if (!form.kb_ids.length) {
    ElMessage.warning('至少绑定一个知识库')
    return
  }
  saving.value = true
  try {
    const body = {
      name: form.name.trim(),
      description: form.description || null,
      emoji: form.emoji || '🤖',
      kb_ids: form.kb_ids,
      provider: form.provider,
      model: null,
      prompt_overrides: cleanOverrides(),
      retrieve_config: { top_k: retrieveCfg.top_k, rerank_top_n: retrieveCfg.rerank_top_n },
      is_published: form.is_published,
      is_public: form.is_public,
    }
    if (editingId.value) {
      await agentApi.adminUpdate(editingId.value, body)
      ElMessage.success('已保存，已发布的智能体立即生效')
    } else {
      await agentApi.adminCreate(body)
      ElMessage.success('已创建')
    }
    editorVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

function cleanOverrides(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const k of PROMPT_KEYS) {
    const v = (form.prompt_overrides[k] ?? '').trim()
    if (v) out[k] = v
  }
  return out
}

async function togglePublish(a: AgentItem) {
  const target = !a.is_published
  try {
    await ElMessageBox.confirm(
      target
        ? `发布「${a.name}」后，所有用户即可在前台使用它。确认发布？`
        : `下线后前台用户将无法新建该智能体的对话。确认下线？`,
      target ? '发布' : '下线',
      { type: 'warning' },
    )
  } catch {
    return
  }
  await agentApi.adminPublish(a.id, target)
  await load()
  ElMessage.success(target ? '已发布' : '已下线')
}

async function remove(a: AgentItem) {
  try {
    await ElMessageBox.confirm(
      `删除「${a.name}」？历史会话会保留，但无法继续提问。`,
      '删除智能体',
      { type: 'warning' },
    )
  } catch {
    return
  }
  await agentApi.adminDelete(a.id)
  await load()
  ElMessage.success('已删除')
}

async function openTest(a: AgentItem) {
  testing.value = a
  testVisible.value = true
  testResult.value = null
  if (!testQuestion.value) testQuestion.value = ''
}

async function runTest() {
  if (!testing.value || !testQuestion.value.trim()) {
    ElMessage.warning('请输入测试问题')
    return
  }
  testRunning.value = true
  try {
    testResult.value = await agentApi.adminTest(testing.value.id, testQuestion.value.trim())
  } finally {
    testRunning.value = false
  }
}

onMounted(load)
</script>

<style scoped>
/* 与前台一致的设计语言：暖白纸面、墨色文字、松绿点缀、双层阴影的拟物卡片 */
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.head-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.head-icon {
  width: 42px;
  height: 42px;
  border-radius: 13px;
  display: grid;
  place-items: center;
  color: #2f6b57;
  background: linear-gradient(165deg, #edf2ef, #dfe8e3);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.85),
    0 1px 2px rgba(23, 24, 26, 0.06),
    0 8px 18px rgba(23, 24, 26, 0.06);
}
.head h2 {
  margin: 0 0 3px;
  font-size: 18px;
  letter-spacing: 0.2px;
  color: #17181a;
}
.sub {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: #6b7076;
}

/* ---------- 按钮（拟物实体 / 幽灵 / 软危险） ---------- */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 13px;
  border: 1px solid transparent;
  border-radius: 10px;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.18s ease, color 0.15s, border-color 0.15s;
}
.btn:active {
  transform: scale(0.96);
}
.btn-primary {
  color: #fff;
  background: linear-gradient(180deg, #3d7f68, #2f6b57);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 1px 2px rgba(23, 24, 26, 0.16),
    0 8px 18px rgba(47, 107, 87, 0.22);
}
.btn-primary:hover {
  transform: translateY(-1px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 2px 4px rgba(23, 24, 26, 0.18),
    0 12px 24px rgba(47, 107, 87, 0.28);
}
.btn-ghost {
  color: #3c4248;
  background: #fff;
  border-color: #e4e1db;
  box-shadow: 0 1px 2px rgba(23, 24, 26, 0.05);
}
.btn-ghost:hover {
  transform: translateY(-1px);
  color: #2f6b57;
  border-color: #c9d6cf;
  box-shadow: 0 6px 14px rgba(23, 24, 26, 0.09);
}
.btn-soft-danger {
  color: #a54b4b;
  background: transparent;
}
.btn-soft-danger:hover {
  background: #f6e7e5;
  color: #8c3737;
}

/* ---------- 卡片网格 ---------- */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}
.card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 18px;
  border: 1px solid #eceae4;
  border-radius: 16px;
  background: linear-gradient(180deg, #ffffff 0%, #fdfcfa 100%);
  box-shadow:
    0 1px 2px rgba(23, 24, 26, 0.04),
    0 12px 28px rgba(23, 24, 26, 0.06);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.card:hover {
  transform: translateY(-3px);
  box-shadow:
    0 2px 4px rgba(23, 24, 26, 0.05),
    0 20px 38px rgba(23, 24, 26, 0.11);
}
.card-top {
  display: flex;
  align-items: center;
  gap: 12px;
}
.emoji-badge {
  width: 48px;
  height: 48px;
  flex: 0 0 48px;
  display: grid;
  place-items: center;
  font-size: 23px;
  border-radius: 15px;
  background: linear-gradient(165deg, #f0f3f1, #e4ebe7);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.9),
    inset 0 -1px 0 rgba(23, 24, 26, 0.05),
    0 1px 2px rgba(23, 24, 26, 0.07);
}
.title {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.title strong {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.2px;
  color: #17181a;
}
.tags {
  display: flex;
  gap: 6px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 20px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
}
.chip .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.85;
}
.chip-live {
  color: #22664f;
  background: #dceee5;
}
.chip-draft {
  color: #6d7278;
  background: #eeece8;
}
.chip-private {
  color: #9a6b1c;
  background: #f6ecd9;
}

.desc {
  margin: 0;
  min-height: 38px;
  font-size: 12.5px;
  line-height: 1.7;
  color: #5b6068;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.meta {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 0;
  padding: 11px 12px;
  list-style: none;
  border: 1px solid #f0eee9;
  border-radius: 12px;
  background: rgba(247, 246, 243, 0.7);
}
.meta li {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: 12px;
  color: #6b7076;
}
.meta svg {
  flex: 0 0 auto;
  color: #9aa0a6;
}
.text-ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ops {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
}
.ops .btn {
  height: 30px;
  padding: 0 12px;
  font-size: 12px;
}
.ops .btn-soft-danger {
  margin-left: auto;
}
</style>
