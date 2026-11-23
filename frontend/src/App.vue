<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { auth, ui } from './lib/store'
import { api } from './lib/api'

const route = useRoute()
const router = useRouter()
const open = ref(false)
const globalState = ref('loading')

const nav = [
  { path: '/overview', label: '总览', icon: '◎' },
  { path: '/accounts', label: '账户管理', icon: '◉' },
  { path: '/personas', label: '人设管理', icon: '☺' },
  { path: '/chats', label: '会话列表', icon: '✉' },
  { path: '/contacts', label: '联系人', icon: '⚇' },
  { path: '/proactive', label: '主动任务', icon: '↗' },
  { path: '/style', label: '风格档案', icon: '≋' },
  { path: '/voice', label: '语音管理', icon: '♪' },
  { path: '/logs', label: '日志与用量', icon: '▤' },
  { path: '/settings', label: '系统设置', icon: '⚙' },
]

const title = computed(() => route.meta.title || '')
const isLogin = computed(() => route.path === '/login')

async function refreshState() {
  if (!auth.token) { globalState.value = '未登录'; return }
  try {
    const list = await api.get('/api/accounts')
    const on = list.filter((a) => a.ai_enabled && a.enabled).length
    globalState.value = `${on}/${list.length} 在跑`
  } catch {
    globalState.value = '—'
  }
}

async function stopAll() {
  if (!confirm('确认全部停发？所有账号的 AI 会立刻停止回复。')) return
  try {
    const r = await api.post('/api/control/stop_all', {})
    ui.ok(`已停发 ${r.stopped} 个账号`)
    refreshState()
  } catch (e) { ui.err(e.message) }
}

async function resumeAll() {
  try {
    const r = await api.post('/api/control/resume_all', {})
    ui.ok(`已恢复 ${r.resumed} 个账号`)
    refreshState()
  } catch (e) { ui.err(e.message) }
}

function logout() {
  auth.logout()
  router.push('/login')
}

onMounted(refreshState)
</script>

<template>
  <div v-if="isLogin" class="min-h-full"><router-view /></div>

  <div v-else class="flex min-h-full">
    <!-- 侧栏 -->
    <aside
      class="fixed inset-y-0 left-0 z-40 w-60 border-r border-line bg-ink-900 transition-transform lg:static lg:translate-x-0"
      :class="open ? 'translate-x-0' : '-translate-x-full'"
    >
      <div class="flex h-14 items-center gap-2 border-b border-line px-4">
        <div class="grid h-7 w-7 place-items-center rounded-md bg-accent text-ink-950 text-sm font-bold">A</div>
        <div class="leading-tight">
          <div class="text-sm font-semibold text-white">AI 托管控制台</div>
          <div class="mono text-[10px] text-slate-500">account operator</div>
        </div>
      </div>
      <nav class="space-y-0.5 p-2">
        <router-link
          v-for="n in nav" :key="n.path" :to="n.path"
          class="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-slate-400 hover:bg-ink-800 hover:text-white"
          :class="route.path.startsWith(n.path) ? 'bg-ink-800 text-white' : ''"
          @click="open = false"
        >
          <span class="w-4 text-center text-slate-500">{{ n.icon }}</span>{{ n.label }}
        </router-link>
      </nav>
      <div class="absolute bottom-0 left-0 right-0 border-t border-line p-3">
        <div class="mb-2 flex items-center justify-between text-[11px] text-slate-500">
          <span>运行状态</span><span class="mono text-accent">{{ globalState }}</span>
        </div>
        <div class="flex gap-1.5">
          <button class="btn-danger btn-sm flex-1" @click="stopAll">全部停发</button>
          <button class="btn-ghost btn-sm flex-1" @click="resumeAll">恢复</button>
        </div>
      </div>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-ink-950/90 px-4 backdrop-blur">
        <button class="btn-ghost btn-sm lg:hidden" @click="open = !open">☰</button>
        <h1 class="text-base font-semibold text-white">{{ title }}</h1>
        <div class="ml-auto flex items-center gap-3">
          <span class="hidden text-[11px] text-slate-500 sm:block">当前登录</span>
          <span class="mono text-xs text-slate-300">{{ auth.username || 'admin' }}</span>
          <button class="btn-ghost btn-sm" @click="logout">退出</button>
        </div>
      </header>

      <main class="flex-1 p-4 sm:p-6">
        <router-view />
      </main>
    </div>

    <div class="fixed bottom-4 right-4 z-50 space-y-2">
      <div
        v-for="t in ui.toasts" :key="t.id"
        class="rounded-lg border px-3.5 py-2.5 text-sm shadow-xl"
        :class="t.type === 'err' ? 'border-danger/40 bg-danger/15 text-danger' : 'border-accent-dim bg-ink-800 text-accent'"
      >{{ t.msg }}</div>
    </div>
  </div>
</template>
