<template>
  <div>
    <div class="head">
      <div>
        <h2>智能体</h2>
        <p class="sub">
          把模型、知识库、提示词、检索参数封装成一个可发布的整体。前台用户只能选用，不能改配置。
        </p>
      </div>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>&nbsp;新建智能体
      </el-button>
    </div>

    <el-empty v-if="!loading && !list.length" description="还没有智能体，点右上角新建一个" />

    <div class="grid">
      <div v-for="a in list" :key="a.id" class="card">
        <div class="card-top">
          <span class="emoji">{{ a.emoji }}</span>
          <div class="title">
            <strong>{{ a.name }}</strong>
            <div class="tags">
              <el-tag size="small" :type="a.is_published ? 'success' : 'info'" effect="plain">
                {{ a.is_published ? '已发布' : '草稿' }}
              </el-tag>
              <el-tag v-if="!a.is_public" size="small" type="warning" effect="plain">
                非公开
              </el-tag>
            </div>
          </div>
        </div>
        <p class="desc">{{ a.description || '（无描述）' }}</p>
        <div class="meta">
          <span>📚 {{ a.kb_names.length ? a.kb_names.join('、') : '未绑定知识库' }}</span>
          <span>🧠 {{ a.model || '跟随全局默认' }}</span>
          <span>💬 {{ a.session_count }} 会话 / {{ a.message_count }} 消息</span>
        </div>
        <div class="ops">
          <el-button size="small" @click="openTest(a)">试跑</el-button>
          <el-button size="small" @click="openEdit(a)">编辑</el-button>
          <el-button
            size="small"
            :type="a.is_published ? 'warning' : 'success'"
            plain
            @click="togglePublish(a)"
          >
            {{ a.is_published ? '下线' : '发布' }}
          </el-button>
          <el-button size="small" type="danger" plain @click="remove(a)">删除</el-button>
        </div>
      </div>
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
import { Plus } from '@element-plus/icons-vue'

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
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}
.head h2 {
  margin: 0 0 4px;
  font-size: 18px;
}
.sub {
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}
.card {
  padding: 14px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card-top {
  display: flex;
  align-items: center;
  gap: 10px;
}
.emoji {
  font-size: 26px;
}
.title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tags {
  display: flex;
  gap: 4px;
}
.desc {
  margin: 0;
  font-size: 12.5px;
  color: var(--el-text-color-secondary);
  min-height: 18px;
}
.meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.ops {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}
.hint {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
.test-out {
  margin: 12px 0 0;
  padding: 12px 14px;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.8;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
}
.cites {
  margin-top: 10px;
}
.cite-title {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}
.cite-item {
  padding: 6px 10px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-lighter);
  border-radius: 6px;
  margin-bottom: 4px;
}
</style>
