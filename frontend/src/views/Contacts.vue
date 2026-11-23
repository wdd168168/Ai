<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { fmtTime, ui } from '../lib/store'

const items = ref([])
const accounts = ref([])
const accountId = ref('')
const q = ref('')
const total = ref(0)

async function load() {
  try {
    const p = new URLSearchParams({ size: 50 })
    if (accountId.value) p.set('account_id', accountId.value)
    if (q.value) p.set('q', q.value)
    const d = await api.get(`/api/contacts?${p}`)
    items.value = d.items
    total.value = d.total
  } catch (e) { ui.err(e.message) }
}

async function toggleBlacklist(c) {
  try { await api.patch(`/api/contacts/${c.id}`, { blacklist: !c.blacklist }); load() } catch (e) { ui.err(e.message) }
}
async function toggleAi(c) {
  try { await api.patch(`/api/contacts/${c.id}`, { ai_enabled: !c.ai_enabled }); load() } catch (e) { ui.err(e.message) }
}
async function mute(c) {
  try { await api.patch(`/api/contacts/${c.id}`, { mute_minutes: 120 }); ui.ok('已静默 2 小时'); load() } catch (e) { ui.err(e.message) }
}
async function coldStart(c) {
  try { await api.post(`/api/contacts/${c.id}/cold_start`, {}); ui.ok('画像已按历史记录重建'); load() } catch (e) { ui.err(e.message) }
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
      <input v-model="q" class="input max-w-[220px]" placeholder="搜索名字 / 备注" @keyup.enter="load" />
      <button class="btn-ghost" @click="load">刷新</button>
      <span class="text-[11px] text-slate-500">共 {{ total }} 个联系人</span>
    </div>

    <div class="card overflow-x-auto">
      <table class="w-full min-w-[980px]">
        <thead><tr>
          <th class="th">联系人</th><th class="th">语言</th><th class="th">亲密度</th>
          <th class="th">兴趣</th><th class="th">最后互动</th><th class="th">状态</th><th class="th">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="c in items" :key="c.id" class="row">
            <td class="td">
              <div class="font-medium text-slate-100">{{ c.name }}</div>
              <div class="mono text-[11px] text-slate-600">{{ c.username ? '@' + c.username : c.tg_id }}</div>
            </td>
            <td class="td text-xs">{{ c.lang || '—' }}</td>
            <td class="td">
              <div class="flex items-center gap-2">
                <div class="h-1.5 w-16 overflow-hidden rounded bg-ink-700">
                  <div class="h-full bg-accent" :style="{ width: c.intimacy + '%' }"></div>
                </div>
                <span class="mono text-[11px]">{{ c.intimacy }}</span>
              </div>
            </td>
            <td class="td">
              <span v-for="i in (c.interests || []).slice(0, 3)" :key="i.topic" class="badge mr-1 bg-ink-700 text-slate-300">{{ i.topic }}</span>
              <span v-if="!(c.interests || []).length" class="text-xs text-slate-600">—</span>
            </td>
            <td class="td text-xs text-slate-500">{{ fmtTime(c.last_msg_at) }}</td>
            <td class="td">
              <span v-if="c.blacklist" class="badge bg-danger/15 text-danger">黑名单</span>
              <span v-else-if="c.mute_until" class="badge bg-warn/15 text-warn">静默中</span>
              <span v-else-if="c.ai_enabled" class="badge bg-ok/15 text-ok">AI 正常</span>
              <span v-else class="badge bg-slate-700/40 text-slate-400">AI 关</span>
            </td>
            <td class="td">
              <div class="flex flex-wrap gap-1">
                <router-link :to="`/chats/${c.id}`" class="btn-ghost btn-sm">对话</router-link>
                <button class="btn-ghost btn-sm" @click="toggleAi(c)">{{ c.ai_enabled ? '暂停' : '恢复' }}</button>
                <button class="btn-ghost btn-sm" @click="mute(c)">静默2h</button>
                <button class="btn-ghost btn-sm" @click="coldStart(c)">重建画像</button>
                <button class="btn-danger btn-sm" @click="toggleBlacklist(c)">{{ c.blacklist ? '移出' : '拉黑' }}</button>
              </div>
            </td>
          </tr>
          <tr v-if="!items.length"><td class="td text-slate-500" colspan="7">还没有联系人。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
