<template>
  <div class="page">
    <div class="hello">
      <div>
        <h2 class="page-title">你好，{{ store.displayName }}</h2>
        <p class="text-muted">{{ greeting }}　·　当前角色：{{ store.roleNames.join('、') || '无' }}</p>
      </div>
      <el-button type="primary" @click="router.push('/chat')">
        <el-icon><ChatDotRound /></el-icon>&nbsp;开始提问
      </el-button>
    </div>

    <el-row :gutter="16" class="stats">
      <el-col :xs="12" :sm="12" :md="6" v-for="s in statCards" :key="s.label">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-icon" :style="{ background: s.bg, color: s.color }">
              <el-icon :size="20"><component :is="s.icon" /></el-icon>
            </div>
            <div>
              <div class="stat-value">{{ s.value }}</div>
              <div class="stat-label">{{ s.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :md="14" :xs="24">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="flex-between">
              <span>最近更新的知识库</span>
              <el-link type="primary" :underline="false" @click="router.push('/admin/kb')">
                全部
              </el-link>
            </div>
          </template>
          <el-empty v-if="!loading && kbs.length === 0" description="还没有知识库" :image-size="70">
            <el-button type="primary" size="small" @click="router.push('/admin/kb')">去创建</el-button>
          </el-empty>
          <div v-else v-loading="loading">
            <div v-for="kb in kbs.slice(0, 5)" :key="kb.id" class="kb-row" @click="router.push(`/admin/kb/${kb.id}`)">
              <div class="kb-main">
                <el-icon color="#3b82f6"><Collection /></el-icon>
                <span class="kb-name">{{ kb.name }}</span>
                <el-tag v-if="kb.sensitivity === 'confidential'" type="danger" size="small" effect="plain">
                  涉密
                </el-tag>
              </div>
              <div class="kb-meta">
                {{ kb.doc_count }} 文档 · {{ kb.chunk_count }} 切片
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :md="10" :xs="24">
        <el-card shadow="never" class="panel">
          <template #header><span>近 7 天用量</span></template>
          <div v-if="!usagePerm" class="text-muted">没有查看用量统计的权限</div>
          <div v-else v-loading="usageLoading">
            <div class="usage-row">
              <span>调用次数</span><b>{{ usage.total_calls }}</b>
            </div>
            <div class="usage-row">
              <span>输入 token</span><b>{{ usage.total_prompt_tokens.toLocaleString() }}</b>
            </div>
            <div class="usage-row">
              <span>输出 token</span><b>{{ usage.total_completion_tokens.toLocaleString() }}</b>
            </div>
            <div v-if="usage.items.length" class="usage-models">
              <div v-for="it in usage.items.slice(0, 4)" :key="`${it.scene}-${it.model}`" class="usage-model">
                <el-tag size="small" effect="plain">{{ it.scene }}</el-tag>
                <span class="text-muted">{{ it.model }}</span>
                <span>{{ it.calls }} 次</span>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { adminApi, type UsageSummary } from '@/api/admin'
import { kbApi, type KnowledgeBase } from '@/api/kb'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const store = useUserStore()

const kbs = ref<KnowledgeBase[]>([])
const loading = ref(false)
const usageLoading = ref(false)
const usage = ref<UsageSummary>({
  days: 7,
  total_calls: 0,
  total_prompt_tokens: 0,
  total_completion_tokens: 0,
  items: [],
})

const usagePerm = computed(() => store.hasPerm('audit:read'))

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了，注意休息'
  if (h < 12) return '上午好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const statCards = computed(() => [
  {
    label: '知识库',
    value: kbs.value.length,
    icon: 'Collection',
    bg: '#e8f0ff',
    color: '#3b82f6',
  },
  {
    label: '文档总数',
    value: kbs.value.reduce((s, k) => s + k.doc_count, 0),
    icon: 'Document',
    bg: '#eafaf1',
    color: '#18a058',
  },
  {
    label: '切片总数',
    value: kbs.value.reduce((s, k) => s + k.chunk_count, 0),
    icon: 'Files',
    bg: '#fff4e6',
    color: '#e6a23c',
  },
  {
    label: '7 天调用',
    value: usage.value.total_calls,
    icon: 'DataLine',
    bg: '#f4ecff',
    color: '#8b5cf6',
  },
])

onMounted(async () => {
  loading.value = true
  try {
    kbs.value = await kbApi.list()
  } finally {
    loading.value = false
  }

  if (usagePerm.value) {
    usageLoading.value = true
    try {
      usage.value = await adminApi.usage(7)
    } catch {
      /* 无权限或接口异常时保持默认值 */
    } finally {
      usageLoading.value = false
    }
  }
})
</script>

<style scoped>
.hello {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
  flex-wrap: wrap;
  gap: 12px;
}

.stats {
  margin-bottom: 16px;
}

.stat-card {
  border-radius: 10px;
  margin-bottom: 12px;
}

.stat-inner {
  display: flex;
  align-items: center;
  gap: 14px;
}

.stat-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-value {
  font-size: 22px;
  font-weight: 600;
  line-height: 1.2;
}

.stat-label {
  font-size: 12px;
  color: #8a919f;
}

.panel {
  border-radius: 10px;
  margin-bottom: 16px;
}

.kb-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 6px;
  border-bottom: 1px dashed #eef0f4;
  cursor: pointer;
}

.kb-row:last-child {
  border-bottom: none;
}

.kb-row:hover {
  background: #f8fafd;
}

.kb-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.kb-name {
  font-size: 14px;
}

.kb-meta {
  font-size: 12px;
  color: #8a919f;
}

.usage-row {
  display: flex;
  justify-content: space-between;
  padding: 7px 0;
  border-bottom: 1px dashed #eef0f4;
  font-size: 13px;
}

.usage-row b {
  font-size: 15px;
}

.usage-models {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.usage-model {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
}
</style>
