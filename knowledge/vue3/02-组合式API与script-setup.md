# Vue3 组合式 API 与 script setup

## 两种写法并存

Vue3 同时支持 Options API 和 Composition API。老项目可以沿用 Options API，新项目推荐 Composition API + `<script setup>`。

## script setup 是什么

`<script setup>` 是编译时语法糖：里面的顶层变量、函数、import 进来的组件，都会自动暴露给模板，不需要 `return`、不需要 `components` 注册。

```vue
<script setup>
import { ref } from 'vue'
import UserCard from './UserCard.vue'

const name = ref('张三')
function greet() {
  console.log('hello', name.value)
}
</script>

<template>
  <UserCard />
  <button @click="greet">{{ name }}</button>
</template>
```

等价于普通 `<script>` 里 `setup()` 返回对象 + `components: { UserCard }` 的写法，但代码量少一半。

## 为什么叫"组合式"

核心思想是**按逻辑关注点组织代码**，而不是按选项类型（data、methods、computed）切开。

一个"用户列表 + 搜索 + 分页"的功能，用 Options API 时相关代码散落在 data、computed、methods、watch 四个区块里；用 Composition API 可以全部写在一起，或者抽成一个组合函数。

## 组合函数（composable）的写法

约定：文件名以 `use` 开头，返回响应式状态和方法。

```js
// composables/useCounter.js
import { ref, computed } from 'vue'

export function useCounter(initial = 0) {
  const count = ref(initial)
  const double = computed(() => count.value * 2)

  function inc() {
    count.value++
  }
  function reset() {
    count.value = initial
  }

  return { count, double, inc, reset }
}
```

在组件中使用：

```vue
<script setup>
import { useCounter } from '@/composables/useCounter'
const { count, double, inc } = useCounter(10)
</script>
```

组合函数是 Vue3 最重要的复用手段，取代了 Vue2 的 mixin。相比 mixin，它有三个优势：来源清晰（能看出变量从哪个函数来）、可传参、不会命名冲突。

## 三个编译宏

`<script setup>` 里可以用三个不需要 import 的宏：

| 宏 | 作用 |
|---|---|
| `defineProps` | 声明 props |
| `defineEmits` | 声明事件 |
| `defineExpose` | 暴露给父组件（默认组件内部是封闭的） |

```vue
<script setup>
const props = defineProps({
  title: { type: String, required: true },
  count: { type: Number, default: 0 },
})
const emit = defineEmits(['update', 'delete'])

function onSave() {
  emit('update', props.count + 1)
}
</script>
```

Vue 3.3 之后还支持 `defineOptions`（声明 `name`、`inheritAttrs`）和 `defineSlots`（声明插槽类型）。

## 与 Options API 的对应关系

| Options API | Composition API |
|---|---|
| `data()` | `ref` / `reactive` |
| `computed` | `computed()` |
| `methods` | 普通函数 |
| `watch` | `watch()` / `watchEffect()` |
| `mounted` | `onMounted()` |
| `components` | 直接 import |
| `props` | `defineProps()` |
| `this.$emit` | `defineEmits()` |

## 常见误区

**1. 以为 `<script setup>` 里能用 `this`**

不能。`this` 在 `<script setup>` 中是 `undefined`，所有状态都通过变量直接访问。

**2. 把 ref 当普通变量传给子组件**

传 `props` 时如果传 `count`（ref 本身），子组件拿到的是 ref 对象；传 `count.value` 才是值。模板中直接写 `:count="count"`，Vue 会自动解包。

**3. 在 `<script setup>` 里定义组件名**

默认组件名从文件名推断。需要显式命名时用 `defineOptions({ name: 'Xxx' })`，而不是再写一个 `<script>`。

**4. 混用两种 API**

技术上可以在同一个组件里写 `<script setup>` 和 `<script>`，但除了需要 `export default` 的场景（如继承 mixin），不建议混用，会造成"状态到底在哪"的困惑。
