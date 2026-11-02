# Vue Router 4 使用要点

## 安装与基础配置

```js
// router/index.js
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'Home', component: () => import('@/views/Home.vue') },
  { path: '/user/:id', name: 'User', component: () => import('@/views/User.vue'), props: true },
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('@/views/404.vue') },
]

const router = createRouter({
  history: createWebHistory(),   // 需要服务端把 404 回退到 index.html
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

export default router
```

`createWebHistory` 是 HTML5 History 模式，地址干净（无 `#`），但**必须配置服务端回退**，否则刷新子路由会 404。若无法改服务端，用 `createWebHashHistory`。

## 动态路由与传参

```js
{ path: '/user/:id', component: User, props: true }
```

三种取参方式：

```js
// 组合式 API
import { useRoute } from 'vue-router'
const route = useRoute()
const id = route.params.id        // 路径参数，一定是字符串
const q = route.query.keyword     // 查询参数
```

用 `props: true` 后，组件里直接 `defineProps(['id'])`，不用依赖 `useRoute()`，组件更好测试、更可复用。

**注意**：组件复用时（同一路由不同参数），`onMounted` 不会重新触发。要监听参数变化：

```js
watch(() => route.params.id, (id) => load(id), { immediate: true })
```

或者在 `<router-view>` 上加 `:key="route.fullPath"` 强制重建组件。前者更省，后者更简单，按场景选择。

## 路由守卫

### 全局守卫

```js
router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (to.meta.requiresAuth && !auth.token) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  if (to.meta.roles && !to.meta.roles.includes(auth.role)) {
    return { name: 'Forbidden' }
  }

  return true   // 放行
})
```

Vue Router 4 的返回值语义（与 v3 的 `next()` 不同，这点最容易写错）：

| 返回值 | 含义 |
|---|---|
| `undefined` / `true` | 放行 |
| `false` | 取消导航，留在原地 |
| 路由地址对象或字符串 | 重定向到新地址 |
| `Error` 实例 | 取消导航并触发 `router.onError` |

**不要同时用返回值和 `next()`**。v4 保留 `next` 只是为了兼容，混用会导致行为不可预测。

### 路由独享守卫

```js
{ path: '/admin', component: Admin, beforeEnter: (to) => checkPermission(to) }
```

### 组件内守卫

```js
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'

onBeforeRouteLeave((to, from) => {
  if (formDirty.value) return confirm('有未保存的修改，确定离开？')
})
```

`onBeforeRouteLeave` 是防"填了一半表单误点离开"的标准做法。

## 懒加载与分包

```js
{ path: '/report', component: () => import('@/views/Report.vue') }
```

动态 `import` 会让打包工具把该页面单独切成一个 chunk，首屏只加载必要的代码。**全部路由都用懒加载**是常规做法，除了首页。

命名 chunk 便于排查：

```js
component: () => import(/* webpackChunkName: "report" */ '@/views/Report.vue')
```

## 编程式导航

```js
import { useRouter } from 'vue-router'
const router = useRouter()

router.push('/user/1')
router.push({ name: 'User', params: { id: 1 } })
router.replace('/login')      // 不产生历史记录
router.back()
```

`push` 返回 Promise，重复导航到当前路由会抛 `NavigationDuplicated` 错误（v4 中已被静默处理，但仍建议加 `.catch(() => {})` 在某些版本中更稳）。

## 路由元信息与权限菜单

```js
{
  path: 'users',
  meta: { title: '用户管理', icon: 'User', perm: 'user:read' },
}
```

常见做法是：路由表带 `meta.perm`，侧边栏菜单由路由表过滤生成，同时 `beforeEach` 再校验一次。

**关键**：前端根据 `meta.perm` 隐藏菜单只是体验优化，**后端必须再校验一次**。只靠前端隐藏的权限等于没有权限——用户直接改地址栏就能进。

## 常见问题

**1. 刷新后 404**

`createWebHistory` 需要服务端配置：Nginx 用 `try_files $uri $uri/ /index.html;`。

**2. 守卫里用了未初始化的 store**

`beforeEach` 在 `app.use(router)` 之前可能执行，此时 Pinia 还未挂载。要么在守卫内调用 `useStore()`（Pinia 已 install 的情况下可行），要么确保 `app.use(pinia)` 在 `app.use(router)` 之前。

**3. 嵌套路由的子路由不显示**

父组件模板里必须写 `<router-view />`，否则子路由无处渲染。这是最常见的"路由配了但页面空白"的原因。

**4. 命名路由跳转时 params 丢失**

用 `name` + `params` 跳转可以传对象参数，但用 `path` + `params` 时 params 会被忽略。要传 params 必须用 `name`。
