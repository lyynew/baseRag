<template>
  <div class="err-page">
    <el-result icon="warning" title="403" sub-title="你的账号没有访问该页面的权限">
      <template #extra>
        <el-button type="primary" @click="router.replace('/')">返回首页</el-button>
        <el-button @click="router.back()">返回上一页</el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<style scoped>
.err-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
