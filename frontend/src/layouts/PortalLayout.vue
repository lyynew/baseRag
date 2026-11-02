<template>
  <div class="portal-shell">
    <router-view />
  </div>
</template>

<script setup lang="ts">
// 前台只做容器：顶栏、侧栏、用户菜单都由页面自己控制，
// 这样对话页可以做到真正的全屏沉浸，而不是被固定顶栏切掉一截。
</script>

<style scoped>
.portal-shell {
  height: 100vh;
  overflow: hidden;
  background: var(--paper, #f7f6f3);
}
</style>
