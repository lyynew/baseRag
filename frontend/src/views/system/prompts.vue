<template>
  <div class="prompt-page">
    <!-- 左：模板列表 -->
    <aside class="tpl-list">
      <div class="tpl-head">
        <span>提示词模板</span>
        <el-tooltip
          content="提示词决定模型怎么说话，改坏会让回答质量整体下滑，建议先预览再保存"
          placement="right"
        >
          <el-icon class="hint"><QuestionFilled /></el-icon>
        </el-tooltip>
      </div>

      <div
        v-for="item in list"
        :key="item.code"
        class="tpl-item"
        :class="{ active: item.code === current?.code }"
        @click="selectTemplate(item)"
      >
        <div class="tpl-title">
          <span class="name">{{ item.name }}</span>
          <el-tag v-if="item.is_customized" size="small" type="warning" effect="plain">
            已改
          </el-tag>
        </div>
        <div class="tpl-meta">
          <code>{{ item.code }}</code>
          <span>v{{ item.version || 0 }}</span>
        </div>
      </div>

      <div class="tpl-tip">
        变量用 <code v-pre>{{name}}</code> 形式，保存时会校验，拼错会直接报错。
      </div>
    </aside>

    <!-- 右：编辑器 -->
    <section v-if="current" class="editor">
      <header class="ed-head">
        <div class="ed-title">
          <h3>{{ current.name }}</h3>
          <code class="code">{{ current.code }}</code>
          <el-tag size="small" :type="current.is_customized ? 'warning' : 'info'" effect="plain">
            {{ current.is_customized ? '已自定义' : '内置默认' }}
          </el-tag>
          <span class="ver">v{{ current.version || 0 }}</span>
        </div>
        <div class="ed-actions">
          <el-button size="small" @click="openPreview">预览</el-button>
          <el-button size="small" @click="openTest">试跑</el-button>
          <el-button size="small" @click="openVersions">版本历史</el-button>
          <el-button size="small" :disabled="!current.is_customized" @click="doReset">
            恢复默认
          </el-button>
          <el-button
            size="small"
            type="primary"
            :loading="saving"
            :disabled="!dirty || !canWrite"
            @click="doSave"
          >
            保存
          </el-button>
        </div>
      </header>

      <p v-if="current.description" class="ed-desc">{{ current.description }}</p>

      <div class="var-bar">
        <span class="var-label">可插入变量</span>
        <button v-for="v in variables" :key="v.name" class="var-chip" :title="v.desc" @click="insertVar(v.name)">
          {{ wrapVar(v.name) }}
        </button>
      </div>

      <el-input
        ref="editorRef"
        v-model="draft"
        type="textarea"
        :rows="20"
        resize="vertical"
        class="ed-input"
        placeholder="在这里编辑提示词…"
        @input="dirty = true"
      />

      <div class="ed-foot">
        <span>{{ draft.length }} 字符 · 约 {{ Math.round(draft.length * 1.5) }} token</span>
        <span v-if="!canWrite" class="ro">当前账号只读，无权修改提示词</span>
        <span v-else-if="dirty" class="warn">有未保存的修改</span>
      </div>
    </section>

    <!-- 预览抽屉 -->
    <el-drawer v-model="previewVisible" title="渲染预览" size="620px">
      <div class="pv">
        <el-alert type="info" :closable="false" show-icon>
          预览不调用模型，不产生费用。下面按样例值填充变量后的最终 system 内容。
        </el-alert>

        <div class="pv-vars">
          <div v-for="v in variables" :key="v.name" class="pv-var">
            <label>{{ wrapVar(v.name) }}</label>
            <el-input v-model="previewValues[v.name]" size="small" :placeholder="v.desc" />
          </div>
        </div>

        <div class="pv-actions">
          <el-button size="small" @click="runPreview">重新渲染</el-button>
          <span v-if="preview" class="pv-stat">
            {{ preview.chars }} 字符 · 约 {{ preview.tokens_estimate }} token
          </span>
        </div>

        <el-alert
          v-if="preview?.missing?.length"
          type="warning"
          :closable="false"
          show-icon
          :title="`以下变量未提供值，会原样保留：${preview.missing.join('、')}`"
        />

        <pre class="pv-out">{{ preview?.rendered || '（点击重新渲染）' }}</pre>
      </div>
    </el-drawer>

    <!-- 试跑对话框 -->
    <el-dialog v-model="testVisible" title="试跑当前提示词" width="680px">
      <el-form label-width="92px">
        <el-form-item label="测试问题">
          <el-input v-model="testQuestion" placeholder="例如：出差住宿标准是多少" />
        </el-form-item>
        <el-form-item label="检索知识库">
          <el-select v-model="testKbId" clearable placeholder="不选则不检索，仅测提示词本身" style="width: 100%">
            <el-option v-for="kb in kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
      </el-form>

      <el-alert type="warning" :closable="false" show-icon>
        试跑会真实调用模型（用当前编辑中的内容，无需先保存），通常消耗几百 token。
      </el-alert>

      <div v-if="testResult" class="test-out">
        <div class="test-meta">
          {{ testResult.model }} · {{ testResult.latency_ms }}ms ·
          {{ testResult.prompt_tokens }}+{{ testResult.completion_tokens }} token ·
          资料 {{ testResult.sources }} 条
        </div>
        <pre class="pv-out">{{ testResult.answer }}</pre>
      </div>

      <template #footer>
        <el-button @click="testVisible = false">关闭</el-button>
        <el-button type="primary" :loading="testing" @click="runTest">开始试跑</el-button>
      </template>
    </el-dialog>

    <!-- 版本历史 -->
    <el-drawer v-model="versionVisible" title="版本历史" size="720px">
      <el-empty v-if="!versions.length" description="还没有版本记录" />
      <div v-for="v in versions" :key="v.version" class="ver-item">
        <div class="ver-head">
          <div>
            <strong>v{{ v.version }}</strong>
            <span class="ver-time">{{ fmt(v.created_at) }}</span>
            <el-tag v-if="v.note" size="small" effect="plain">{{ v.note }}</el-tag>
          </div>
          <el-button size="small" :disabled="!canWrite" @click="doRollback(v.version)">
            回滚到此版本
          </el-button>
        </div>
        <pre class="ver-body">{{ v.content }}</pre>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type InputInstance } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'

import { promptApi, type PromptItem, type PromptVar, type PromptVersionItem, type PromptPreview, type PromptTestResult } from '@/api/prompts'
import { kbApi, type KnowledgeBase } from '@/api/kb'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const canWrite = computed(() => store.hasPerm('config:write'))

const list = ref<PromptItem[]>([])
const current = ref<PromptItem | null>(null)
const draft = ref('')
const dirty = ref(false)
const saving = ref(false)
const variables = ref<PromptVar[]>([])
const editorRef = ref<InputInstance>()

const previewVisible = ref(false)
const preview = ref<PromptPreview | null>(null)
const previewValues = reactive<Record<string, string>>({})

const testVisible = ref(false)
const testing = ref(false)
const testQuestion = ref('')
const testKbId = ref<number | undefined>(undefined)
const testResult = ref<PromptTestResult | null>(null)
const kbs = ref<KnowledgeBase[]>([])

const versionVisible = ref(false)
const versions = ref<PromptVersionItem[]>([])

function fmt(s: string | null) {
  return s ? new Date(s).toLocaleString('zh-CN') : '-'
}

/** 生成 {{var}} 文本。不能在模板里直接写字符串拼接，Vue 会把 "{{" 当成插值边界 */
function wrapVar(name: string) {
  return `{{${name}}}`
}

async function load() {
  list.value = await promptApi.list()
  if (!current.value && list.value.length) {
    await selectTemplate(list.value[0])
  } else if (current.value) {
    const fresh = list.value.find((x) => x.code === current.value!.code)
    if (fresh) current.value = fresh
  }
}

async function selectTemplate(item: PromptItem) {
  if (dirty.value) {
    try {
      await ElMessageBox.confirm('当前有未保存的修改，切换后会丢失，继续？', '提示', {
        type: 'warning',
      })
    } catch {
      return
    }
  }
  const detail = await promptApi.detail(item.code)
  current.value = detail
  draft.value = detail.content
  dirty.value = false
  // 预览样例值默认填一份，避免每次手输
  for (const v of detail.variables || []) {
    if (!previewValues[v]) {
      previewValues[v] = SAMPLE[v] ?? ''
    }
  }
}

const SAMPLE: Record<string, string> = {
  question: '出差住宿标准是多少',
  context: '[1] 一线城市每晚不超过 600 元，二线城市不超过 400 元。',
  kb_name: '员工手册',
  sources: '1',
  history: '（多轮对话历史）',
}

function insertVar(name: string) {
  const token = `{{${name}}}`
  const el = editorRef.value?.$el?.querySelector('textarea') as HTMLTextAreaElement | null
  if (!el) {
    draft.value += token
    dirty.value = true
    return
  }
  const start = el.selectionStart ?? draft.value.length
  const end = el.selectionEnd ?? start
  draft.value = draft.value.slice(0, start) + token + draft.value.slice(end)
  dirty.value = true
  requestAnimationFrame(() => {
    el.focus()
    el.setSelectionRange(start + token.length, start + token.length)
  })
}

async function doSave() {
  if (!current.value) return
  try {
    await ElMessageBox.prompt('可选：说明这次改了什么，会记入版本历史', '保存提示词', {
      inputPlaceholder: '例如：加强引用要求，禁止总结性开头',
      inputValue: '',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    }).then(async ({ value }) => {
      saving.value = true
      const saved = await promptApi.save(current.value!.code, {
        content: draft.value,
        note: value || undefined,
      })
      current.value = saved
      draft.value = saved.content
      dirty.value = false
      await load()
      ElMessage.success(`已保存为 v${saved.version}，下一次提问立即生效`)
    })
  } catch (e: unknown) {
    // 用户取消 prompt 时不提示；接口错误由拦截器统一处理
    if (e === 'cancel' || e === 'close') return
  } finally {
    saving.value = false
  }
}

async function doReset() {
  try {
    await ElMessageBox.confirm(
      '恢复默认会用内置内容覆盖当前提示词（版本号继续递增，历史仍可回滚）。继续？',
      '恢复默认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  const r = await promptApi.reset(current.value!.code)
  current.value = r
  draft.value = r.content
  dirty.value = false
  await load()
  ElMessage.success('已恢复为内置默认')
}

async function openPreview() {
  previewVisible.value = true
  preview.value = null
  await runPreview()
}

async function runPreview() {
  if (!current.value) return
  preview.value = await promptApi.preview(current.value.code, {
    content: draft.value,
    values: { ...previewValues },
  })
}

async function openTest() {
  testVisible.value = true
  testResult.value = null
  if (!testQuestion.value) testQuestion.value = SAMPLE.question
  if (!kbs.value.length) {
    try {
      kbs.value = await kbApi.list()
    } catch {
      kbs.value = []
    }
  }
}

async function runTest() {
  if (!current.value || !testQuestion.value.trim()) {
    ElMessage.warning('请填写测试问题')
    return
  }
  testing.value = true
  try {
    testResult.value = await promptApi.test(current.value.code, {
      question: testQuestion.value.trim(),
      content: draft.value,
      kb_id: testKbId.value,
    })
  } finally {
    testing.value = false
  }
}

async function openVersions() {
  versionVisible.value = true
  versions.value = await promptApi.versions(current.value!.code)
}

async function doRollback(version: number) {
  try {
    await ElMessageBox.confirm(
      `回滚会把 v${version} 的内容作为新版本提交，不会删除现有历史。继续？`,
      '回滚',
      { type: 'warning' },
    )
  } catch {
    return
  }
  const r = await promptApi.rollback(current.value!.code, version)
  current.value = r
  draft.value = r.content
  dirty.value = false
  await load()
  await openVersions()
  ElMessage.success(`已回滚，生成 v${r.version}`)
}

onMounted(async () => {
  variables.value = await promptApi.variables()
  await load()
})
</script>

<style scoped>
.prompt-page {
  display: flex;
  height: calc(100vh - var(--app-header-h) - 32px);
  gap: 14px;
}
.tpl-list {
  width: 236px;
  flex: 0 0 236px;
  display: flex;
  flex-direction: column;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: #fff;
  overflow: auto;
}
.tpl-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 4px 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}
.hint {
  color: var(--el-text-color-placeholder);
  cursor: help;
}
.tpl-item {
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.tpl-item:hover {
  background: var(--el-fill-color-light);
}
.tpl-item.active {
  background: var(--el-color-primary-light-9);
}
.tpl-title {
  display: flex;
  align-items: center;
  gap: 6px;
}
.tpl-title .name {
  font-size: 13px;
  font-weight: 500;
}
.tpl-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 3px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
.tpl-meta code,
.code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.tpl-tip {
  margin-top: auto;
  padding: 10px 4px 2px;
  font-size: 11px;
  line-height: 1.7;
  color: var(--el-text-color-placeholder);
}
.tpl-tip code {
  padding: 1px 4px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}

.editor {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: 14px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: #fff;
}
.ed-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.ed-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ed-title h3 {
  margin: 0;
  font-size: 15px;
}
.ed-title .code {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}
.ver {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.ed-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.ed-desc {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.var-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin: 12px 0 8px;
}
.var-label {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.var-chip {
  padding: 2px 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border: 1px solid transparent;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s;
}
.var-chip:hover {
  border-color: var(--el-color-primary-light-5);
}
.ed-input :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  line-height: 1.75;
}
.ed-foot {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.ed-foot .warn {
  color: var(--el-color-warning);
}
.ed-foot .ro {
  color: var(--el-color-danger);
}

.pv,
.test-out {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.pv-vars {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 12px;
}
.pv-var label {
  display: block;
  margin-bottom: 3px;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.pv-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.pv-stat {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.pv-out {
  margin: 0;
  padding: 12px 14px;
  max-height: 420px;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px;
  line-height: 1.85;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--el-text-color-primary);
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
}
.test-out .test-meta {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.ver-item {
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}
.ver-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.ver-time {
  margin: 0 8px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.ver-body {
  margin: 0;
  padding: 8px 10px;
  max-height: 180px;
  overflow: auto;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  background: var(--el-fill-color-lighter);
  border-radius: 6px;
}
</style>
