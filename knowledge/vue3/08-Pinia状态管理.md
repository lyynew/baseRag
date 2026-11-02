# Pinia 状态管理

## 为什么用 Pinia

Pinia 是 Vue 官方推荐的状态管理库，取代 Vuex。相比 Vuex 3/4 的核心改进：

1. **没有 mutations**：直接改 state，少一层样板代码
2. **完整的 TypeScript 支持**：类型自动推断，不需要手写类型
3. **模块扁平**：每个 store 独立，不需要嵌套 modules
4. **支持组合式写法**：可以和 Composition API 风格一致
5. **支持多个 store 互相引用**、支持服务端渲染

## 安装

```js
// main.js
import { createPinia } from 'pinia'
app.use(createPinia())
```

## 两种定义风格

### 选项式（类似 Vuex）

```js
// stores/user.js
import { defineStore } from 'pinia'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: '',
    profile: null,
    permissions: [],
  }),
  getters: {
    isLogin: (state) => !!state.token,
    // 访问其他 getter 需要显式声明 this 类型（TS）
    isAdmin() {
      return this.permissions.includes('admin')
    },
  },
  actions: {
    async login(payload) {
      const data = await api.login(payload)
      this.token = data.token
      this.profile = data.user
    },
    logout() {
      this.token = ''
      this.profile = null
      this.permissions = []
    },
  },
})
```

### 组合式（推荐）

```js
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useUserStore = defineStore('user', () => {
  const token = ref('')
  const profile = ref(null)
  const permissions = ref([])

  const isLogin = computed(() => !!token.value)
  const isAdmin = computed(() => permissions.value.includes('admin'))

  async function login(payload) {
    const data = await api.login(payload)
    token.value = data.token
    profile.value = data.user
  }

  function logout() {
    token.value = ''
    profile.value = null
    permissions.value = []
  }

  return { token, profile, permissions, isLogin, isAdmin, login, logout }
})
```

组合式写法的好处是与组件内代码完全一致，组合函数可以直接复用；缺点是**必须 return 所有要暴露的成员**，漏了就是 `undefined`。

## 在组件中使用

```vue
<script setup>
import { storeToRefs } from 'pinia'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

// 解构 state/getter 必须用 storeToRefs，否则丢失响应性
const { token, isLogin } = storeToRefs(userStore)

// action 直接解构没问题（它们是普通函数）
const { logout } = userStore
</script>
```

`storeToRefs` 是这里最关键的一点。直接 `const { token } = userStore` 拿到的是普通字符串，之后 store 里 token 变了，组件不会更新。这个 bug 不会报错，只会表现为"数据变了但界面不变"。

## state 的修改方式

```js
const store = useUserStore()

store.token = 'abc'              // 直接赋值
store.$patch({ token: 'abc' })   // 批量，只触发一次更新
store.$patch((state) => {        // 函数式，适合需要基于旧值的修改
  state.list.push(item)
})
store.$reset()                   // 重置为初始值（组合式写法需自己实现 reset）
```

**不要整体替换 state**，`store.$state = {...}` 虽然可行，但会丢掉原有的响应式代理引用。

## 跨 store 引用

```js
export const useCartStore = defineStore('cart', () => {
  const user = useUserStore()   // 在 store 内部调用其他 store
  const items = ref([])
  const owner = computed(() => user.profile?.name)
  return { items, owner }
})
```

在 store 定义函数内部调用 `useXxxStore()` 是安全的，因为这个函数在组件 setup 阶段才执行。但不要在模块顶层直接调用，那时 Pinia 还没安装。

## 持久化

Pinia 本身不带持久化。两种做法：

**手动**：在 action 里写 localStorage，或监听 `$subscribe`：

```js
store.$subscribe((mutation, state) => {
  localStorage.setItem('user', JSON.stringify(state))
})
```

**插件**：`pinia-plugin-persistedstate`，在 store 上加 `persist: true` 即可。

无论哪种，**只持久化必要的字段**（token、主题、语言），不要把整个 store 塞进 localStorage：里面有接口数据，容易过期，也占空间。

## 常见误区

**1. 所有状态都放 Pinia**

组件内的临时状态（弹窗开关、输入框内容、当前 tab）应该留在组件里。全局 store 只放真正跨页面共享的东西。什么都往 store 塞会导致 store 变成一个巨大的全局变量池，改一处影响一片。

**2. 用 store 存派生数据**

```js
// 反模式：两个状态可能不同步
const items = ref([])
const total = ref(0)
function add(i) { items.value.push(i); total.value = items.value.length }
```

应使用 `computed` 派生 `total`，永远只有一个数据源。

**3. 在 setup 之外调用 useStore**

`useUserStore()` 依赖当前活跃的 Pinia 实例。在路由守卫、工具函数、`setTimeout` 回调里直接调用可能拿不到实例。这些场景应在函数内部调用（延迟到执行时），而不是模块顶层。

**4. 忘记 storeToRefs**

如前所述，解构 state 不加 `storeToRefs` 会丢响应性，且没有任何报错。
