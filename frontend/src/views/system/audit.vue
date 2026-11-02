<template>
  <div class="page">
    <el-row :gutter="16" class="summary">
      <el-col :xs="12" :md="6">
        <el-card shadow="never" class="stat">
          <div class="stat-value">{{ usage.total_calls }}</div>
          <div class="text-muted">近 {{ days }} 天调用</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :md="6">
        <el-card shadow="never" class="stat">
          <div class="stat-value">{{ usage.total_prompt_tokens.toLocaleString() }}</div>
          <div class="text-muted">输入 token</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :md="6">
        <el-card shadow="never" class="stat">
          <div class="stat-value">{{ usage.total_completion_tokens.toLocaleString() }}</div>
          <div class="text-muted">输出 token</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :md="6">
        <el-card shadow="never" class="stat">
          <div class="stat-value">{{ auditLogs.length }}</div>
          <div class="text-muted">近期审计记录</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :md="12" :xs="24">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="flex-between">
              <span>用量构成</span>
              <el-select v-model="days" size="small" style="width: 110px" @change="loadUsage">
                <el-option :value="7" label="近 7 天" />
                <el-option :value="14" label="近 14 天" />
                <el-option :value="30" label="近 30 天" />
              </el-select>
            </div>
          </template>
          <el-table :data="usage.items" size="small" empty-text="暂无调用记录">
            <el-table-column prop="scene" label="场景" width="110" />
            <el-table-column prop="model" label="模型" min-width="140" show-overflow-tooltip />
            <el-table-column prop="calls" label="次数" width="80" />
            <el-table-column label="输入" width="100">
              <template #default="{ row }">{{ row.prompt_tokens.toLocaleString() }}</template>
            </el-table-column>
            <el-table-column label="输出" width="100">
              <template #default="{ row }">{{ row.completion_tokens.toLocaleString() }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :md="12" :xs="24">
        <el-card shadow="never" class="panel">
          <template #header><span>每日调用趋势</span></template>
          <div v-if="daily.items.length === 0" class="text-muted">暂无数据</div>
          <div v-else class="bars">
            <div v-for="d in daily.items" :key="d.date" class="bar-row">
              <span class="bar-date">{{ d.date.slice(5) }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: `${barWidth(d.calls)}%` }" />
              </div>
              <span class="bar-value">{{ d.calls }}</span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="panel">
      <template #header>
        <div class="flex-between">
          <span>审计日志</span>
          <div>
            <el-input
              v-model="actionFilter"
              placeholder="按 action 前缀过滤，如 kb."
              size="small"
              clearable
              style="width: 200px"
              @keyup.enter="loadAudit"
              @clear="loadAudit"
            />
            <el-button size="small" style="margin-left: 8px" @click="loadAudit">查询</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="auditLogs" size="small" empty-text="暂无记录">
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ fmt(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="operator_name" label="操作人" width="120" />
        <el-table-column prop="action" label="动作" width="180" />
        <el-table-column label="对象" width="160">
          <template #default="{ row }">
            <span v-if="row.target_type">{{ row.target_type }}#{{ row.target_id ?? '-' }}</span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="变更" min-width="260">
          <template #default="{ row }">
            <el-popover v-if="row.before || row.after" placement="left" width="420" trigger="click">
              <template #reference>
                <el-button link type="primary" size="small">查看差异</el-button>
              </template>
              <div class="diff">
                <div class="diff-block">
                  <div class="diff-title">变更前</div>
                  <pre>{{ pretty(row.before) }}</pre>
                </div>
                <div class="diff-block">
                  <div class="diff-title">变更后</div>
                  <pre>{{ pretty(row.after) }}</pre>
                </div>
              </div>
            </el-popover>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="ip" label="IP" width="130" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { adminApi, type AuditLogItem, type DailyUsage, type UsageSummary } from '@/api/admin'

const days = ref(7)
const usage = ref<UsageSummary>({
  days: 7,
  total_calls: 0,
  total_prompt_tokens: 0,
  total_completion_tokens: 0,
  items: [],
})
const daily = ref<DailyUsage>({ days: 14, items: [] })
const auditLogs = ref<AuditLogItem[]>([])
const loading = ref(false)
const actionFilter = ref('')

const maxCalls = computed(() => Math.max(1, ...daily.value.items.map((d) => d.calls)))

function barWidth(v: number): number {
  return Math.max(4, Math.round((v / maxCalls.value) * 100))
}

function fmt(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function pretty(obj: Record<string, unknown> | null): string {
  return obj ? JSON.stringify(obj, null, 2) : '—'
}

async function loadUsage() {
  usage.value = await adminApi.usage(days.value)
}

async function loadAudit() {
  loading.value = true
  try {
    auditLogs.value = await adminApi.auditLogs({
      action: actionFilter.value || undefined,
      days: 30,
      limit: 100,
    })
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadUsage(), loadAudit()])
  daily.value = await adminApi.usageDaily(14).catch(() => ({ days: 14, items: [] }))
})
</script>

<style scoped>
.summary {
  margin-bottom: 4px;
}

.stat {
  border-radius: 10px;
  margin-bottom: 12px;
}

.stat-value {
  font-size: 22px;
  font-weight: 600;
}

.panel {
  border-radius: 10px;
  margin-bottom: 16px;
}

.bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.bar-date {
  width: 44px;
  color: #8a919f;
}

.bar-track {
  flex: 1;
  height: 16px;
  background: #f2f4f8;
  border-radius: 4px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #6fa8ff, #3b82f6);
  border-radius: 4px;
  transition: width 0.3s;
}

.bar-value {
  width: 40px;
  text-align: right;
  color: #5a6270;
}

.diff {
  display: flex;
  gap: 10px;
}

.diff-block {
  flex: 1;
  min-width: 0;
}

.diff-title {
  font-size: 12px;
  color: #8a919f;
  margin-bottom: 4px;
}

.diff pre {
  margin: 0;
  font-size: 11px;
  background: #f7f9fc;
  padding: 8px;
  border-radius: 6px;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
