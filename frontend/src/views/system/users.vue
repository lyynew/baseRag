<template>
  <div class="page">
    <div class="page-toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索用户名/昵称"
        clearable
        style="width: 220px"
        @keyup.enter="load"
        @clear="load"
      />
      <el-button @click="load">查询</el-button>
      <div style="flex: 1" />
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>&nbsp;新建用户
      </el-button>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="users" size="small">
        <el-table-column prop="username" label="用户名" width="140" />
        <el-table-column prop="nickname" label="昵称" width="130" />
        <el-table-column prop="email" label="邮箱" min-width="160" show-overflow-tooltip />
        <el-table-column label="角色" width="180">
          <template #default="{ row }">
            <el-tag
              v-for="r in row.roles"
              :key="r"
              size="small"
              :type="r === 'super_admin' ? 'danger' : r === 'admin' ? 'warning' : 'info'"
              effect="plain"
              style="margin-right: 4px"
            >
              {{ r }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近登录" width="150">
          <template #default="{ row }">{{ row.last_login_at ? fmt(row.last_login_at) : '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" size="small" @click="openReset(row)">重置密码</el-button>
            <el-button
              link
              :type="row.is_active ? 'warning' : 'success'"
              size="small"
              @click="toggleActive(row)"
            >
              {{ row.is_active ? '禁用' : '启用' }}
            </el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑用户' : '新建用户'" width="520px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="editing" placeholder="登录名，创建后不可改" />
        </el-form-item>
        <el-form-item v-if="!editing" label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="8~64 位，含字母和数字" />
        </el-form-item>
        <el-form-item label="昵称">
          <el-input v-model="form.nickname" maxlength="64" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" maxlength="128" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role_codes" multiple style="width: 100%">
            <el-option v-for="r in roles" :key="r.code" :label="`${r.name}（${r.code}）`" :value="r.code" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resetVisible" title="重置密码" width="420px">
      <el-input v-model="newPassword" type="password" show-password placeholder="8~64 位，含字母和数字" />
      <p class="text-muted" style="margin-top: 8px">重置后该用户所有登录会话会立即失效。</p>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitReset">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'

import { adminApi, type AdminUser, type RoleItem } from '@/api/admin'

const users = ref<AdminUser[]>([])
const roles = ref<RoleItem[]>([])
const loading = ref(false)
const saving = ref(false)
const keyword = ref('')
const dialogVisible = ref(false)
const editing = ref(false)
const resetVisible = ref(false)
const newPassword = ref('')
const formRef = ref<FormInstance>()
let editingId = 0
let resetUserId = 0

const form = reactive({
  username: '',
  password: '',
  nickname: '',
  email: '',
  role_codes: ['user'] as string[],
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

function fmt(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function load() {
  loading.value = true
  try {
    users.value = await adminApi.users({ keyword: keyword.value || undefined })
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = false
  editingId = 0
  Object.assign(form, { username: '', password: '', nickname: '', email: '', role_codes: ['user'] })
  dialogVisible.value = true
}

function openEdit(row: AdminUser) {
  editing.value = true
  editingId = row.id
  Object.assign(form, {
    username: row.username,
    password: '',
    nickname: row.nickname || '',
    email: row.email || '',
    role_codes: [...row.roles],
  })
  dialogVisible.value = true
}

async function submit() {
  if (!formRef.value) return
  const ok = await formRef.value.validate().catch(() => false)
  if (!ok) return

  saving.value = true
  try {
    if (editing.value) {
      await adminApi.updateUser(editingId, {
        nickname: form.nickname,
        email: form.email,
        role_codes: form.role_codes,
      })
      ElMessage.success('已保存')
    } else {
      await adminApi.createUser({
        username: form.username,
        password: form.password,
        nickname: form.nickname || undefined,
        email: form.email || undefined,
        role_codes: form.role_codes,
      })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function toggleActive(row: AdminUser) {
  if (row.is_active) {
    try {
      await ElMessageBox.confirm(`禁用「${row.username}」后该用户将无法登录，且现有会话失效。`, '确认', {
        type: 'warning',
      })
    } catch {
      return
    }
  }
  await adminApi.updateUser(row.id, { is_active: !row.is_active })
  ElMessage.success('已更新')
  await load()
}

function openReset(row: AdminUser) {
  resetUserId = row.id
  newPassword.value = ''
  resetVisible.value = true
}

async function submitReset() {
  if (!newPassword.value) {
    ElMessage.warning('请输入新密码')
    return
  }
  saving.value = true
  try {
    await adminApi.resetPassword(resetUserId, newPassword.value)
    ElMessage.success('密码已重置')
    resetVisible.value = false
  } finally {
    saving.value = false
  }
}

async function remove(row: AdminUser) {
  try {
    await ElMessageBox.confirm(`确定删除「${row.username}」？该操作为软删除。`, '确认', { type: 'warning' })
  } catch {
    return
  }
  await adminApi.removeUser(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(async () => {
  await load()
  roles.value = await adminApi.roles().catch(() => [])
})
</script>
