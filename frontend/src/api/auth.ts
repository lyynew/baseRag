import http from './request'

export interface LoginPayload {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface RoleBrief {
  code: string
  name: string
}

export interface UserInfo {
  id: number
  username: string
  nickname: string | null
  email: string | null
  avatar: string | null
  is_superuser: boolean
  roles: RoleBrief[]
  permissions: string[]
}

export const authApi = {
  login(payload: LoginPayload) {
    return http.post<TokenResponse>('/auth/login', payload).then((r) => r.data)
  },
  me() {
    return http.get<UserInfo>('/auth/me').then((r) => r.data)
  },
  logout(refreshToken: string) {
    return http.post('/auth/logout', { refresh_token: refreshToken })
  },
  changePassword(oldPassword: string, newPassword: string) {
    return http.post('/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  },
}
