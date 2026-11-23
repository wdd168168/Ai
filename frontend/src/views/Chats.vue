<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { fmtTime, ui } from '../lib/store'

const items = ref([])
const accounts = ref([])
const accountId = ref('')
const q = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (accountId.value) params.set('account_id', accountId.value)
    if (q.value) params.set('q', q.value)
    const d = await api.get(`/api/chats?${params}`)
    items.value = d.items
  } catch (e) { ui.err(e.message) } finally { loading.value = false }
}
onMounted(async () => {
  try { accounts.value = await api.get('/api/accounts') } catch {}
  load()
})
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <select v-model="accountId" class="input max-w-[200px]" @change="load">
        <option value="">全部账号</option>
        <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.label }}</option>
      </select>
      <input v-model="q" class="input max-w-[240px]" placeholder="搜名字 / 用户名" @keyup.enter="load" />
      <button class="btn-ghost" @click="load">刷新</button>
      <span class="text-[11px] text-slate-500">{{ items.length }} 个会话</span>
    </div>

    <div class="card divide-y divide-line/70">
      <div v-if="loading" class="p-4 text-sm text-slate-500">加载中…</div>
      <router-link
        v-for="c in items" :key="c.contact_id" :to="`/chats/${c.contact_id}`"
        class="flex items-center gap-3 p-3.5 hover:bg-ink-800/60"
      >
        <div class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink-700 text-xs text-slate-300">
          {{ (c.name || '?').slice(0, 1) }}
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="truncate text-sm font-medium text-slate-100">{{ c.name }}</span>
            <span v-if="c.username" class="mono text-[11px] text-slate-600">@{{ c.username }}</span>
            <span class="badge" :class="c.ai_active ? 'bg-ok/15 text-ok' : 'bg-warn/15 text-warn'">
              {{ c.blacklist ? '黑名单' : c.ai_active ? 'AI 接管中' : '已暂停' }}
            </span>
            <span class="badge bg-ink-700 text-slate-400">{{ c.lang || '—' }}</span>
          </div>
          <div class="mt-0.5 truncate text-xs text-slate-500">
            {{ c.last_direction === 'out' ? '我：' : '' }}{{ c.last_message }}
          </div>
        </div>
        <div class="shrink-0 text-right">
          <div class="text-[11px] text-slate-500">{{ fmtTime(c.last_time) }}</div>
          <div class="text-[11px] text-slate-600">亲密度 {{ c.intimacy }}</div>
        </div>
      </router-link>
      <div v-if="!items.length && !loading" class="p-6 text-center text-xs text-slate-500">还没有会话。账号上线并有人发消息后才会有记录。</div>
    </div>
  </div>
</template>
