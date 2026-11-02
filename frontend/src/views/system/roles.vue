<template>
  <div class="page">
    <el-row :gutter="16">
      <el-col :md="8" :xs="24">
        <el-card shadow="never" header="角色">
          <div
            v-for="r in roles"
            :key="r.code"
            class="role-item"
            :class="{ active: r.code === current?.code }"
            @click="select(r)"
          >
            <div class="flex-between">
              <div>
                <span class="role-name">{{ r.name }}</span>
                <el-tag v-if="r.is_builtin" size="small" effect="plain" type="info" style="margin-left: 6px">
                  内置
                </el-tag>
              </div>
              <span class="text-muted">{{ r.user_count }} 人</span>
            </div>
            <div class="text-muted">{{ r.code }}</div>
          </div>
        </el-card>
      </el-col>

      <el-col :md="16" :xs="24">
        <el-card shadow="never">
          <template #header>
            <div class="flex-between">
              <span>权限配置 · {{ current?.name || '未选择' }}</span>
              <el-button
                type="primary"
                size="small"
                :loading="saving"
                :disabled="!current || current.code === 'super_admin'"
                @click="save"
              >
                保存
              </el-button>
            </div>
          </template>

          <el-alert
            v-if="current?.code === 'super_admin'"
            type="info"
            :closable="false"
            show-icon
            title="超级管理员恒为全部权限，不可修改（避免把自己锁在系统外）。"
            style="margin-bottom: 14px"
          />

          <div v-for="(items, group) in grouped" :key="group" class="perm-group">
            <div class="group-title">{{ groupLabel(group as string) }}</div>
            <el-checkbox-group v-model="checked" :disabled="current?.code === 'super_admin'">
              <el-checkbox v-for="p in items" :key="p.code" :label="p.code" :value="p.code">
                {{ p.name }}
                <span class="text-muted">{{ p.code }}</span>
              </el-checkbox>
            </el-checkbox-group>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { adminApi, type PermissionItem, type RoleItem } from '@/api/admin'

const roles = ref<RoleItem[]>([])
const permissions = ref<PermissionItem[]>([])
const current = ref<RoleItem | null>(null)
const checked = ref<string[]>([])
const saving = ref(false)

const GROUP_LABELS: Record<string, string> = {
  user: '用户管理',
  role: '角色与权限',
  kb: '知识库',
  doc: '文档',
  config: '系统配置',
  audit: '审计',
  chat: '问答',
}

function groupLabel(g: string): string {
  return GROUP_LABELS[g] || g
}

const grouped = computed(() => {
  const map: Record<string, PermissionItem[]> = {}
  for (const p of permissions.value) {
    if (!map[p.group_name]) map[p.group_name] = []
    map[p.group_name].push(p)
  }
  return map
})

function select(role: RoleItem) {
  current.value = role
  checked.value = [...role.permissions]
}

async function save() {
  if (!current.value) return
  saving.value = true
  try {
    const updated = await adminApi.updateRole(current.value.id, { permissions: checked.value })
    ElMessage.success('权限已保存')
    const idx = roles.value.findIndex((r) => r.id === updated.id)
    if (idx >= 0) roles.value[idx] = updated
    current.value = updated
  } finally {
    saving.value = false
  }
}

watch(
  () => current.value?.code,
  () => {
    if (current.value) checked.value = [...current.value.permissions]
  },
)

onMounted(async () => {
  const [r, p] = await Promise.all([adminApi.roles(), adminApi.permissions()])
  roles.value = r
  permissions.value = p
  if (r.length) select(r.find((x) => x.code === 'admin') || r[0])
})
</script>

<style scoped>
.role-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  border: 1px solid transparent;
  margin-bottom: 8px;
}

.role-item:hover {
  background: #f8fafd;
}

.role-item.active {
  background: #eef4ff;
  border-color: #c7ddff;
}

.role-name {
  font-size: 14px;
  font-weight: 500;
}

.perm-group {
  margin-bottom: 18px;
}

.group-title {
  font-size: 13px;
  font-weight: 600;
  color: #3a4150;
  margin-bottom: 8px;
  padding-left: 2px;
  border-left: 3px solid #3b82f6;
  padding-left: 8px;
}

.perm-group :deep(.el-checkbox) {
  width: 260px;
  margin-right: 0;
}
</style>
