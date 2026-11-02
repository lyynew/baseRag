<template>
  <div class="page">
    <div class="page-toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索知识库"
        :prefix-icon="Search"
        clearable
        style="width: 240px"
        @keyup.enter="load"
        @clear="load"
      />
      <el-button @click="load">查询</el-button>
      <div style="flex: 1" />
      <el-button v-if="canWrite" type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>&nbsp;新建知识库
      </el-button>
    </div>

    <el-empty v-if="!loading && list.length === 0" description="还没有知识库，先创建一个吧">
      <el-button v-if="canWrite" type="primary" @click="openCreate">新建知识库</el-button>
    </el-empty>

    <el-row v-else v-loading="loading" :gutter="16">
      <el-col v-for="kb in list" :key="kb.id" :xs="24" :sm="12" :md="8" :lg="6">
        <el-card shadow="hover" class="kb-card" @click="goDetail(kb.id)">
          <div class="kb-head">
            <el-icon :size="18" color="#3b82f6"><Collection /></el-icon>
            <span class="kb-title" :title="kb.name">{{ kb.name }}</span>
            <el-tag v-if="kb.sensitivity === 'confidential'" type="danger" size="small" effect="plain">
              涉密
            </el-tag>
          </div>

          <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>

          <div class="kb-stats">
            <span>{{ kb.doc_count }} 文档</span>
            <el-divider direction="vertical" />
            <span>{{ kb.chunk_count }} 切片</span>
          </div>

          <div class="kb-foot">
            <el-tag size="small" effect="plain" type="info">{{ kb.my_role || 'viewer' }}</el-tag>
            <span class="text-muted">{{ formatTime(kb.updated_at) }}</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="createVisible" title="新建知识库" width="560px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="64" show-word-limit placeholder="如：员工手册" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="切片策略">
          <el-select v-model="form.strategy" style="width: 100%">
            <el-option label="按标题切分（推荐，适合有层级的文档）" value="markdown_header" />
            <el-option label="递归切分（通用）" value="recursive" />
            <el-option label="固定长度" value="fixed" />
          </el-select>
        </el-form-item>
        <el-form-item label="切片长度">
          <el-input-number v-model="form.chunk_size" :min="100" :max="4000" :step="50" />
          <span class="text-muted" style="margin-left: 8px">单位：字符（中文约 1.6 token/字）</span>
        </el-form-item>
        <el-form-item label="重叠长度">
          <el-input-number v-model="form.chunk_overlap" :min="0" :max="500" :step="10" />
        </el-form-item>
        <el-form-item label="召回条数">
          <el-input-number v-model="form.top_k" :min="1" :max="100" />
          <span class="text-muted" style="margin-left: 8px">送入 rerank 的候选数</span>
        </el-form-item>
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="切片参数在文档入库后修改，会导致该库需要全量重建向量并重新计费。"
        />
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'

import { kbApi, type KnowledgeBase } from '@/api/kb'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const store = useUserStore()

const list = ref<KnowledgeBase[]>([])
const loading = ref(false)
const keyword = ref('')
const createVisible = ref(false)
const saving = ref(false)
const formRef = ref<FormInstance>()

const canWrite = computed(() => store.hasPerm('kb:write'))

const form = reactive({
  name: '',
  description: '',
  strategy: 'markdown_header' as 'markdown_header' | 'recursive' | 'fixed',
  chunk_size: 512,
  chunk_overlap: 64,
  top_k: 30,
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
}

function formatTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function load() {
  loading.value = true
  try {
    list.value = await kbApi.list(keyword.value || undefined)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.name = ''
  form.description = ''
  form.strategy = 'markdown_header'
  form.chunk_size = 512
  form.chunk_overlap = 64
  form.top_k = 30
  createVisible.value = true
}

async function submitCreate() {
  if (!formRef.value) return
  const ok = await formRef.value.validate().catch(() => false)
  if (!ok) return

  saving.value = true
  try {
    const kb = await kbApi.create({
      name: form.name,
      description: form.description || undefined,
      chunk_config: {
        strategy: form.strategy,
        chunk_size: form.chunk_size,
        chunk_overlap: form.chunk_overlap,
      },
      retrieve_config: { top_k: form.top_k },
    })
    ElMessage.success('创建成功')
    createVisible.value = false
    await load()
    router.push(`/admin/kb/${kb.id}`)
  } finally {
    saving.value = false
  }
}

function goDetail(id: number) {
  router.push(`/admin/kb/${id}`)
}

onMounted(load)
</script>

<style scoped>
.kb-card {
  border-radius: 10px;
  margin-bottom: 16px;
  cursor: pointer;
  transition: transform 0.15s;
}

.kb-card:hover {
  transform: translateY(-2px);
}

.kb-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.kb-title {
  font-size: 15px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-desc {
  font-size: 12px;
  color: #8a919f;
  margin: 0 0 12px;
  height: 34px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.kb-stats {
  font-size: 12px;
  color: #5a6270;
  margin-bottom: 10px;
}

.kb-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
