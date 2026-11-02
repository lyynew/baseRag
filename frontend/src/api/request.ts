import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

const ACCESS_KEY = 'rag_access_token'
const REFRESH_KEY = 'rag_refresh_token'

export const tokenStore = {
  get access(): string {
    return localStorage.getItem(ACCESS_KEY) || ''
  },
  get refresh(): string {
    return localStorage.getItem(REFRESH_KEY) || ''
  },
  set(access: string, refresh?: string): void {
    localStorage.setItem(ACCESS_KEY, access)
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
  },
  clear(): void {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

const http = axios.create({
  baseURL: '/api/v1',
  // 上传大文件与长回答都可能超过 60s，统一放宽
  timeout: 180000,
})

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStore.access
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 刷新令牌单飞：并发的多个 401 只触发一次刷新，其余等待同一个 Promise
let refreshing: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  if (refreshing) return refreshing

  refreshing = (async () => {
    const rt = tokenStore.refresh
    if (!rt) throw new Error('没有 refresh token')
    // 用裸 axios，避免拦截器递归
    const resp = await axios.post('/api/v1/auth/refresh', { refresh_token: rt })
    const data = resp.data as { access_token: string; refresh_token: string }
    tokenStore.set(data.access_token, data.refresh_token)
    return data.access_token
  })()

  try {
    return await refreshing
  } finally {
    refreshing = null
  }
}

function redirectToLogin(): void {
  tokenStore.clear()
  if (location.pathname.startsWith('/login')) return
  const redirect = encodeURIComponent(location.pathname + location.search)
  location.href = `/login?redirect=${redirect}`
}

http.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError<{ code?: string; message?: string; trace_id?: string }>) => {
    const { response, config } = error
    const code = response?.data?.code

    // 401 先尝试静默刷新；凭据错误（登录失败）不刷新
    const isAuthError = response?.status === 401 && code !== 'BAD_CREDENTIALS'
    if (isAuthError && config && !(config as { _retry?: boolean })._retry) {
      try {
        const newToken = await refreshAccessToken()
        ;(config as { _retry?: boolean })._retry = true
        config.headers.Authorization = `Bearer ${newToken}`
        return http(config)
      } catch {
        redirectToLogin()
        return Promise.reject(error)
      }
    }

    if (isAuthError) {
      redirectToLogin()
      return Promise.reject(error)
    }

    // 统一错误提示：后端已把 code/message/trace_id 归一化
    let message = response?.data?.message || error.message || '请求失败'
    if (error.code === 'ECONNABORTED') {
      message = '请求超时，请稍后重试'
    } else if (!response) {
      message = '网络异常，请检查后端服务是否启动'
    }
    const traceId = response?.data?.trace_id
    ElMessage.error(traceId && traceId !== '-' ? `${message}（${traceId}）` : message)
    return Promise.reject(error)
  },
)

export default http
