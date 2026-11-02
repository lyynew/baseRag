<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <el-icon :size="34" color="#3b82f6"><Reading /></el-icon>
        <h1>RAG 知识库系统</h1>
        <p>企业知识检索与智能问答</p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="submit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" clearable />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            :prefix-icon="Lock"
            show-password
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" class="submit" :loading="loading" @click="submit">
            登 录
          </el-button>
        </el-form-item>
      </el-form>

      <div class="tip">
        <span>忘记密码请联系管理员重置</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'

import { hasAdminAccess } from '@/router'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const store = useUserStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function submit() {
  if (!formRef.value) return
  const ok = await formRef.value.validate().catch(() => false)
  if (!ok) return

  loading.value = true
  try {
    await store.login(form.username, form.password)
    ElMessage.success('登录成功')

    // 有后台权限的落到管理后台，普通业务用户直接进对话页
    const redirect = route.query.redirect as string | undefined
    if (redirect) {
      await router.replace(redirect)
    } else {
      await router.replace(hasAdminAccess() ? '/admin/dashboard' : '/chat')
    }
  } catch {
    // 具体错误由 axios 拦截器统一提示
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(1200px 600px at 20% 10%, #e8f0ff 0%, transparent 60%),
    radial-gradient(900px 500px at 90% 90%, #e6f7f2 0%, transparent 55%),
    #f5f7fa;
}

.login-card {
  width: 400px;
  padding: 36px 36px 24px;
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 10px 40px rgba(31, 39, 51, 0.08);
}

.brand {
  text-align: center;
  margin-bottom: 26px;
}

.brand h1 {
  font-size: 20px;
  margin: 10px 0 4px;
  color: #1f2329;
}

.brand p {
  margin: 0;
  font-size: 13px;
  color: #8a919f;
}

.submit {
  width: 100%;
}

.tip {
  text-align: center;
  font-size: 12px;
  color: #a0a6b3;
  margin-top: 4px;
}
</style>
