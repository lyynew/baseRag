<template>
  <el-container class="layout">
    <el-aside :width="collapsed ? '64px' : '216px'" class="aside">
      <div class="brand">
        <el-icon :size="22"><Reading /></el-icon>
        <span v-show="!collapsed" class="brand-text">RAG 知识库</span>
      </div>

      <el-menu
        :default-active="route.path"
        :collapse="collapsed"
        :collapse-transition="false"
        background-color="#1f2733"
        text-color="#c3ccd8"
        active-text-color="#ffffff"
        router
        class="menu"
      >
        <template v-for="item in menus" :key="item.path">
          <el-sub-menu v-if="item.children?.length" :index="item.path">
            <template #title>
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.title }}</span>
            </template>
            <el-menu-item v-for="child in item.children" :key="child.path" :index="child.path">
              <el-icon><component :is="child.icon" /></el-icon>
              <span>{{ child.title }}</span>
            </el-menu-item>
          </el-sub-menu>
          <el-menu-item v-else :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.title }}</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-left">
          <el-icon class="collapse-btn" :size="18" @click="collapsed = !collapsed">
            <Fold v-if="!collapsed" />
            <Expand v-else />
          </el-icon>
          <span class="page-name">{{ route.meta.title || '' }}</span>
        </div>

        <div class="header-right">
          <el-button text size="small" class="portal-entry" @click="router.push('/chat')">
            <el-icon><ChatDotRound /></el-icon>&nbsp;前台对话
          </el-button>
          <el-tag v-if="store.isSuperuser" type="danger" size="small" effect="plain">超管</el-tag>
          <el-tag v-for="n in store.roleNames" :key="n" size="small" effect="plain">{{ n }}</el-tag>

          <el-dropdown trigger="click" @command="onCommand">
            <span class="user-chip">
              <el-avatar :size="26">{{ (store.displayName || 'U').slice(0, 1) }}</el-avatar>
              <span class="user-name">{{ store.displayName }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="password">修改密码</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main">
        <router-view v-slot="{ Component }">
          <keep-alive :max="6">
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </el-main>
    </el-container>

    <el-dialog v-model="pwdVisible" title="修改密码" width="420px">
      <el-form :model="pwdForm" label-width="90px">
        <el-form-item label="原密码">
          <el-input v-model="pwdForm.old" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.new1" type="password" show-password placeholder="8~64 位，含字母和数字" />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="pwdForm.new2" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdLoading" @click="submitPassword">确定</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { authApi } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const collapsed = ref(false)
const pwdVisible = ref(false)
const pwdLoading = ref(false)
const pwdForm = reactive({ old: '', new1: '', new2: '' })

interface MenuNode {
  path: string
  title: string
  icon?: string
  children?: MenuNode[]
}

/** 菜单由后台路由表生成，权限不足的项直接不渲染（后端仍会拦截） */
const menus = computed<MenuNode[]>(() => {
  const root = router.options.routes.find((r) => r.path === '/admin')
  const children = root?.children ?? []
  const items: MenuNode[] = []
  const groups = new Map<string, MenuNode>()

  for (const child of children) {
    const meta = child.meta ?? {}
    if (meta.hidden) continue
    if (meta.perm && !store.hasPerm(meta.perm)) continue

    const node: MenuNode = {
      path: `/admin/${child.path}`,
      title: meta.title ?? '',
      icon: meta.icon,
    }

    if (meta.group) {
      if (!groups.has(meta.group)) {
        const group: MenuNode = {
          path: `group-${meta.group}`,
          title: meta.group,
          icon: 'Setting',
          children: [],
        }
        groups.set(meta.group, group)
        items.push(group)
      }
      groups.get(meta.group)!.children!.push(node)
    } else {
      items.push(node)
    }
  }
  return items
})

async function onCommand(cmd: string) {
  if (cmd === 'logout') {
    try {
      await ElMessageBox.confirm('确定退出登录吗？', '提示', { type: 'warning' })
    } catch {
      return
    }
    await store.logout()
    router.push('/login')
  } else if (cmd === 'password') {
    pwdForm.old = ''
    pwdForm.new1 = ''
    pwdForm.new2 = ''
    pwdVisible.value = true
  }
}

async function submitPassword() {
  if (!pwdForm.old || !pwdForm.new1) {
    ElMessage.warning('请填写完整')
    return
  }
  if (pwdForm.new1 !== pwdForm.new2) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  pwdLoading.value = true
  try {
    await authApi.changePassword(pwdForm.old, pwdForm.new1)
    ElMessage.success('密码已修改，请重新登录')
    pwdVisible.value = false
    await store.logout()
    router.push('/login')
  } finally {
    pwdLoading.value = false
  }
}
</script>

<style scoped>
.layout {
  height: 100vh;
}

.aside {
  background: var(--app-sidebar-bg);
  transition: width 0.2s;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.brand {
  height: var(--app-header-h);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 18px;
  color: #fff;
  font-weight: 600;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  white-space: nowrap;
}

.brand-text {
  font-size: 15px;
  letter-spacing: 0.5px;
}

.menu {
  border-right: none;
  flex: 1;
  overflow-y: auto;
}

.header {
  height: var(--app-header-h);
  background: #fff;
  border-bottom: 1px solid #e8eaef;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.collapse-btn {
  cursor: pointer;
  color: #5a6270;
}

.collapse-btn:hover {
  color: #3b82f6;
}

.page-name {
  font-size: 15px;
  font-weight: 500;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
}

.user-chip:hover {
  background: #f3f5f8;
}

.user-name {
  font-size: 13px;
  color: #1f2329;
}

.main {
  padding: 0;
  background: var(--app-bg);
  overflow-y: auto;
}
</style>
