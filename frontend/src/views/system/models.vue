<template>
  <div class="page">
    <div class="page-toolbar">
      <span class="text-muted">
        模型配置优先于环境变量生效，切换后无需重启服务。密钥加密存储，仅显示后四位。
      </span>
      <div style="flex: 1" />
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>&nbsp;新增模型
      </el-button>
    </div>

    <el-row v-loading="loading" :gutter="16">
      <el-col v-for="m in models" :key="m.id" :xs="24" :md="12" :lg="8">
        <el-card shadow="hover" class="model-card">
          <div class="model-head">
            <div class="flex-between">
              <div class="model-name">
                {{ m.name }}
                <el-tag v-if="m.is_default" type="success" size="small" effect="dark">默认</el-tag>
                <el-tag v-if="!m.enabled" type="info" size="small">已禁用</el-tag>
              </div>
              <el-tag size="small" effect="plain">{{ m.provider }}</el-tag>
            </div>
            <div class="text-muted">{{ m.model }}</div>
          </div>

          <el-descriptions :column="1" size="small" class="model-desc">
            <el-descriptions-item label="接口地址">
              <span class="mono">{{ m.base_url }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="密钥">
              <span class="mono">{{ m.api_key_masked }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="上下文 / 输出">
              {{ m.max_context.toLocaleString() }} / {{ m.max_output.toLocaleString() }}
            </el-descriptions-item>
            <el-descriptions-item label="能力">
              <el-tag v-if="m.supports_json" size="small" effect="plain">JSON</el-tag>
              <el-tag v-if="m.supports_stream" size="small" effect="plain" style="margin-left: 4px">
                流式
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <div v-if="testResults[m.id]" class="test-result">
            <el-alert
              :type="testResults[m.id].ok ? 'success' : 'error'"
              :closable="false"
              :title="
                testResults[m.id].ok
                  ? `连通正常 · ${testResults[m.id].latency_ms}ms · ${testResults[m.id].reply}`
                  : `失败：${testResults[m.id].error}`
              "
            />
          </div>

          <div class="model-actions">
            <el-button size="small" :loading="testingId === m.id" @click="test(m)">测试</el-button>
            <el-button size="small" :disabled="m.is_default" @click="setDefault(m)">设为默认</el-button>
            <el-button size="small" @click="openEdit(m)">编辑</el-button>
            <el-button size="small" type="danger" :disabled="m.is_default" @click="remove(m)">
              删除
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="!loading && models.length === 0" description="还没有配置模型，当前使用 .env 中的默认配置" />

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑模型' : '新增模型'" width="560px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="提供方" prop="provider">
          <el-select v-model="form.provider" :disabled="editing" style="width: 100%">
            <el-option label="DeepSeek" value="deepseek" />
            <el-option label="MiMo（小米）" value="mimo" />
            <el-option label="通义千问" value="qwen" />
            <el-option label="OpenAI" value="openai" />
            <el-option label="其他（OpenAI 兼容）" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="显示名称" prop="name">
          <el-input v-model="form.name" placeholder="如：MiMo V2.6 Flash" />
        </el-form-item>
        <el-form-item label="接口地址" prop="base_url">
          <el-input v-model="form.base_url" placeholder="https://api.xxx.com/v1" />
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="editing ? '留空表示不修改' : 'sk-...'"
          />
        </el-form-item>
        <el-form-item label="模型名" prop="model">
          <el-input v-model="form.model" placeholder="如：mimo-v2.6-flash" />
        </el-form-item>
        <el-form-item label="上下文长度">
          <el-input-number v-model="form.max_context" :min="1024" :max="1048576" :step="1024" />
        </el-form-item>
        <el-form-item label="最大输出">
          <el-input-number v-model="form.max_output" :min="256" :max="65536" :step="256" />
        </el-form-item>
        <el-form-item label="能力">
          <el-checkbox v-model="form.supports_json">支持 JSON 输出</el-checkbox>
          <el-checkbox v-model="form.supports_stream">支持流式</el-checkbox>
          <el-checkbox v-model="form.enabled">启用</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'

import { adminApi, type ModelConfigItem, type ModelTestResult } from '@/api/admin'

const models = ref<ModelConfigItem[]>([])
const loading = ref(false)
const saving = ref(false)
const testingId = ref(0)
const dialogVisible = ref(false)
const editing = ref(false)
const formRef = ref<FormInstance>()
const testResults = reactive<Record<number, ModelTestResult>>({})
let editingId = 0

const form = reactive({
  provider: 'mimo',
  name: '',
  base_url: '',
  api_key: '',
  model: '',
  max_context: 128000,
  max_output: 4096,
  supports_json: true,
  supports_stream: true,
  enabled: true,
})

const rules: FormRules = {
  provider: [{ required: true, message: '请选择提供方', trigger: 'change' }],
  name: [{ required: true, message: '请输入显示名称', trigger: 'blur' }],
  base_url: [{ required: true, message: '请输入接口地址', trigger: 'blur' }],
  model: [{ required: true, message: '请输入模型名', trigger: 'blur' }],
}

async function load() {
  loading.value = true
  try {
    models.value = await adminApi.models()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = false
  editingId = 0
  Object.assign(form, {
    provider: 'mimo',
    name: '',
    base_url: '',
    api_key: '',
    model: '',
    max_context: 128000,
    max_output: 4096,
    supports_json: true,
    supports_stream: true,
    enabled: true,
  })
  dialogVisible.value = true
}

function openEdit(m: ModelConfigItem) {
  editing.value = true
  editingId = m.id
  Object.assign(form, {
    provider: m.provider,
    name: m.name,
    base_url: m.base_url,
    api_key: '',
    model: m.model,
    max_context: m.max_context,
    max_output: m.max_output,
    supports_json: m.supports_json,
    supports_stream: m.supports_stream,
    enabled: m.enabled,
  })
  dialogVisible.value = true
}

async function submit() {
  if (!formRef.value) return
  const ok = await formRef.value.validate().catch(() => false)
  if (!ok) return
  if (!editing.value && !form.api_key) {
    ElMessage.warning('请输入 API Key')
    return
  }

  saving.value = true
  try {
    if (editing.value) {
      const payload: Record<string, unknown> = {
        name: form.name,
        base_url: form.base_url,
        model: form.model,
        max_context: form.max_context,
        max_output: form.max_output,
        supports_json: form.supports_json,
        supports_stream: form.supports_stream,
        enabled: form.enabled,
      }
      if (form.api_key) payload.api_key = form.api_key
      await adminApi.updateModel(editingId, payload)
    } else {
      await adminApi.createModel({
        provider: form.provider,
        name: form.name,
        base_url: form.base_url,
        api_key: form.api_key,
        model: form.model,
        max_context: form.max_context,
        max_output: form.max_output,
        supports_json: form.supports_json,
        supports_stream: form.supports_stream,
        enabled: form.enabled,
      })
    }
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function test(m: ModelConfigItem) {
  testingId.value = m.id
  delete testResults[m.id]
  try {
    testResults[m.id] = await adminApi.testModel(m.id)
  } catch {
    testResults[m.id] = { ok: false, latency_ms: 0, reply: '', error: '请求失败', usage: {} }
  } finally {
    testingId.value = 0
  }
}

async function setDefault(m: ModelConfigItem) {
  try {
    await ElMessageBox.confirm(
      `将「${m.name}」设为全局默认模型？所有新会话将使用它。`,
      '切换默认模型',
      { type: 'warning' },
    )
  } catch {
    return
  }
  await adminApi.setDefaultModel(m.id)
  ElMessage.success('已切换')
  await load()
}

async function remove(m: ModelConfigItem) {
  try {
    await ElMessageBox.confirm(`确定删除「${m.name}」？`, '确认', { type: 'warning' })
  } catch {
    return
  }
  await adminApi.removeModel(m.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<style scoped>
.model-card {
  border-radius: 10px;
  margin-bottom: 16px;
}

.model-head {
  margin-bottom: 10px;
}

.model-name {
  font-size: 15px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}

.model-desc {
  margin-bottom: 8px;
}

.mono {
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
}

.test-result {
  margin-bottom: 10px;
}

.model-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
</style>
