const TOKEN_KEY = 'op_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

async function request(path, { method = 'GET', body, form, raw } = {}) {
  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let payload
  if (form) payload = form
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(path, { method, headers, body: payload })
  if (res.status === 401) {
    setToken('')
    if (location.pathname !== '/login') location.href = '/login'
    throw new Error('登录已过期')
  }
  if (raw) return res
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || `请求失败 ${res.status}`
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return data
}

export const api = {
  get: (p) => request(p),
  post: (p, body) => request(p, { method: 'POST', body: body ?? {} }),
  patch: (p, body) => request(p, { method: 'PATCH', body: body ?? {} }),
  del: (p) => request(p, { method: 'DELETE' }),
  upload: (p, form) => request(p, { method: 'POST', form }),
}

export const authApi = {
  login: (username, password, totp) => api.post('/api/auth/login', { username, password, totp }),
  me: () => api.get('/api/auth/me'),
  changePassword: (old_password, new_password) => api.post('/api/auth/password', { old_password, new_password }),
  setup2fa: () => api.post('/api/auth/2fa/setup', {}),
  enable2fa: (secret, code) => api.post('/api/auth/2fa/enable', { secret, code }),
  disable2fa: (password) => api.post('/api/auth/2fa/disable', { password }),
}
