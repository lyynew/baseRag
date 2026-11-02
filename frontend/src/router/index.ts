import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { tokenStore } from '@/api/request'
import { useUserStore } from '@/stores/user'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    icon?: string
    perm?: string
    hidden?: boolean
    group?: string
    public?: boolean
    /** 标记为管理后台路由：需要任一后台权限才能进入 */
    admin?: boolean
  }
}

const ADMIN_PERMS = ['user:read', 'role:read', 'config:read', 'audit:read', 'kb:write']

/** 是否具备后台准入资格（有任何一项后台权限即可） */
export function hasAdminAccess(): boolean {
  const store = useUserStore()
  if (store.isSuperuser) return true
  return ADMIN_PERMS.some((p) => store.hasPerm(p))
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/index.vue'),
    meta: { public: true, title: '登录' },
  },

  // ---------------- 前台（业务用户） ----------------
  {
    path: '/',
    component: () => import('@/layouts/PortalLayout.vue'),
    redirect: '/chat',
    children: [
      {
        path: 'chat',
        name: 'PortalChat',
        component: () => import('@/views/chat/index.vue'),
        meta: { title: '智能问答' },
      },
      {
        path: 'chat/:sessionId',
        name: 'PortalChatSession',
        component: () => import('@/views/chat/index.vue'),
        meta: { title: '智能问答', hidden: true },
      },
    ],
  },

  // ---------------- 后台（管理端） ----------------
  {
    path: '/admin',
    component: () => import('@/layouts/BasicLayout.vue'),
    redirect: '/admin/dashboard',
    meta: { admin: true },
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/index.vue'),
        meta: { title: '工作台', icon: 'Odometer', admin: true },
      },
      {
        path: 'kb',
        name: 'KnowledgeList',
        component: () => import('@/views/kb/index.vue'),
        meta: { title: '知识库', icon: 'Collection', admin: true },
      },
      {
        path: 'kb/:id',
        name: 'KnowledgeDetail',
        component: () => import('@/views/kb/detail.vue'),
        meta: { title: '知识库详情', hidden: true, admin: true },
      },
      {
        path: 'system/users',
        name: 'Users',
        component: () => import('@/views/system/users.vue'),
        meta: {
          title: '用户管理',
          icon: 'User',
          perm: 'user:read',
          group: '系统管理',
          admin: true,
        },
      },
      {
        path: 'system/roles',
        name: 'Roles',
        component: () => import('@/views/system/roles.vue'),
        meta: {
          title: '角色权限',
          icon: 'Lock',
          perm: 'role:read',
          group: '系统管理',
          admin: true,
        },
      },
      {
        path: 'system/models',
        name: 'Models',
        component: () => import('@/views/system/models.vue'),
        meta: {
          title: '模型配置',
          icon: 'Cpu',
          perm: 'config:read',
          group: '系统管理',
          admin: true,
        },
      },
      {
        path: 'system/prompts',
        name: 'Prompts',
        component: () => import('@/views/system/prompts.vue'),
        meta: {
          title: '提示词管理',
          icon: 'Edit',
          perm: 'config:read',
          group: '系统管理',
          admin: true,
        },
      },
      {
        path: 'system/audit',
        name: 'Audit',
        component: () => import('@/views/system/audit.vue'),
        meta: {
          title: '审计与用量',
          icon: 'DataLine',
          perm: 'audit:read',
          group: '系统管理',
          admin: true,
        },
      },
    ],
  },

  {
    path: '/403',
    name: 'Forbidden',
    component: () => import('@/views/error/403.vue'),
    meta: { public: true, title: '无权访问' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/error/404.vue'),
    meta: { public: true, title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const store = useUserStore()

  if (to.meta.public) {
    if (to.path === '/login' && tokenStore.access) {
      // 已登录再访问登录页：先补齐用户信息，才能判断该回前台还是后台
      if (!store.user) {
        try {
          await store.fetchMe()
        } catch {
          store.reset()
          return true
        }
      }
      return { path: hasAdminAccess() ? '/admin/dashboard' : '/chat' }
    }
    return true
  }

  if (!tokenStore.access) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 刷新页面后 store 为空，需要重新拉取用户信息（权限随之恢复）
  if (!store.user) {
    try {
      await store.fetchMe()
    } catch {
      store.reset()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }

  // 后台路由：无任何后台权限直接 403，而不是渲染出空菜单
  if (to.matched.some((r) => r.meta.admin)) {
    const allowed = store.isSuperuser || ADMIN_PERMS.some((p) => store.hasPerm(p))
    if (!allowed) return { path: '/403' }
  }

  if (to.meta.perm && !store.hasPerm(to.meta.perm)) {
    return { path: '/403' }
  }

  return true
})

router.afterEach((to) => {
  if (to.meta.title) document.title = `${to.meta.title} - RAG 知识库系统`
})

export default router
