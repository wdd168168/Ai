import { reactive } from 'vue'
import { getToken, setToken } from './api'

export const auth = reactive({
  token: getToken(),
  username: localStorage.getItem('op_user') || '',
  totpEnabled: false,
  setLogin(data) {
    this.token = data.access_token
    this.username = data.username
    setToken(data.access_token)
    localStorage.setItem('op_user', data.username)
  },
  logout() {
    this.token = ''
    this.username = ''
    setToken('')
    localStorage.removeItem('op_user')
  },
})

export const ui = reactive({
  toasts: [],
  push(msg, type = 'info') {
    const id = Math.random().toString(36).slice(2)
    this.toasts.push({ id, msg, type })
    setTimeout(() => {
      const i = this.toasts.findIndex((t) => t.id === id)
      if (i >= 0) this.toasts.splice(i, 1)
    }, 4200)
  },
  ok(msg) { this.push(msg, 'ok') },
  err(msg) { this.push(msg, 'err') },
})

export function fmtTime(s) {
  if (!s) return '—'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function fmtNum(n) {
  if (n === null || n === undefined) return '0'
  return Number(n).toLocaleString('en-US')
}

export const LANGS = [
  { v: 'zh-CN', label: '简体中文' },
  { v: 'zh-TW', label: '台湾繁体国语' },
  { v: 'nan-TW', label: '台语（闽南语）' },
  { v: 'en', label: '英语' },
  { v: 'vi', label: '越南语' },
  { v: 'km', label: '高棉语' },
]
