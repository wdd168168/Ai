<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../lib/api'
import { ui } from '../lib/store'

const accounts = ref([])
const accountId = ref('')
const profile = ref(null)
const raw = ref('')
const busy = ref(false)
const override = reactive({ avg_sentence_len: '', emoji_rate: '', catchphrases: '' })

async function load() {
  if (!accountId.value) return
  try {
    profile.value = await api.get(`/api/style/${accountId.value}`)
    const ov = profile.value.manual_override || {}
    override.avg_sentence_len = ov.avg_sentence_len ?? ''
    override.emoji_rate = ov.emoji_rate ?? ''
    override.catchphrases = (ov.catchphrases || []).join('，')
  } catch (e) { ui.err(e.message) }
}

async function importText() {
  if (!raw.value.trim()) return ui.err('先把历史消息按行粘贴进来')
  busy.value = true
  try {
    const r = await api.post('/api/style/import', { account_id: Number(accountId.value), raw_text: raw.value })
    ui.ok(`导入 ${r.imported} 条，已重建风格`)
    raw.value = ''
    load()
  } catch (e) { ui.err(e.message) } finally { busy.value = false }
}

async function pull() {
  busy.value = true
  try {
    const r = await api.post(`/api/style/${accountId.value}/pull?limit=300`, {})
    ui.ok(`从账号拉了 ${r.pulled} 条本人消息`)
    load()
  } catch (e) { ui.err(e.message) } finally { busy.value = false }
}

async function saveOverride() {
  try {
    await api.patch(`/api/style/${accountId.value}/override`, {
      avg_sentence_len: override.avg_sentence_len === '' ? null : Number(override.avg_sentence_len),
      emoji_rate: override.emoji_rate === '' ? null : Number(override.emoji_rate),
      catchphrases: override.catchphrases ? override.catchphrases.split(/[,，]/).map((s) => s.trim()).filter(Boolean) : null,
    })
    ui.ok('修正已生效')
    load()
  } catch (e) { ui.err(e.message) }
}

onMounted(async () => {
  try {
    accounts.value = await api.get('/api/accounts')
    if (accounts.value.length) { accountId.value = accounts.value[0].id; load() }
  } catch (e) { ui.err(e.message) }
})
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <select v-model="accountId" class="input max-w-[220px]" @change="load">
        <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.label }}</option>
      </select>
      <button class="btn-ghost" @click="pull" :disabled="busy">从账号拉取历史消息</button>
      <button class="btn-ghost" @click="load">刷新</button>
    </div>

    <div v-if="profile" class="grid gap-4 lg:grid-cols-2">
      <div class="card card-pad">
        <h3 class="mb-3 text-sm font-medium text-white">自动分析结果</h3>
        <p class="mb-3 rounded-lg border border-line/70 bg-ink-900 px-3 py-2 text-xs text-slate-300">{{ profile.summary || '样本还不够，先导入或拉取历史消息' }}</p>
        <div class="grid grid-cols-2 gap-2 text-xs">
          <div class="rounded-lg border border-line/70 px-2.5 py-2">
            <div class="text-[10px] text-slate-500">样本数</div><div class="mono text-accent">{{ profile.sample_count }}</div>
          </div>
          <div class="rounded-lg border border-line/70 px-2.5 py-2">
            <div class="text-[10px] text-slate-500">平均句长</div><div class="mono">{{ profile.avg_sentence_len }}</div>
          </div>
          <div class="rounded-lg border border-line/70 px-2.5 py-2">
            <div class="text-[10px] text-slate-500">分段比例</div><div class="mono">{{ (profile.paragraph_ratio * 100).toFixed(0) }}%</div>
          </div>
          <div class="rounded-lg border border-line/70 px-2.5 py-2">
            <div class="text-[10px] text-slate-500">emoji 率</div><div class="mono">{{ (profile.emoji_rate * 100).toFixed(0) }}%</div>
          </div>
        </div>
        <div class="mt-3">
          <div class="mb-1.5 text-[11px] text-slate-500">口头禅</div>
          <div class="flex flex-wrap gap-1">
            <span v-for="c in profile.catchphrases" :key="c" class="badge bg-accent/10 text-accent">{{ c }}</span>
            <span v-if="!profile.catchphrases?.length" class="text-xs text-slate-600">暂无</span>
          </div>
        </div>
        <div class="mt-3">
          <div class="mb-1.5 text-[11px] text-slate-500">标点习惯</div>
          <div class="mono text-xs text-slate-400">{{ (profile.punctuation?.top || []).join('  ') || '—' }}</div>
        </div>
      </div>

      <div class="space-y-3">
        <div class="card card-pad">
          <h3 class="mb-2 text-sm font-medium text-white">手动修正（立即生效，优先级最高）</h3>
          <div class="grid gap-2 sm:grid-cols-3">
            <div><label class="label">平均句长</label><input v-model="override.avg_sentence_len" class="input mono" placeholder="12" /></div>
            <div><label class="label">emoji 率 0-1</label><input v-model="override.emoji_rate" class="input mono" placeholder="0.2" /></div>
            <div><label class="label">口头禅</label><input v-model="override.catchphrases" class="input" placeholder="笑死，真的假的" /></div>
          </div>
          <button class="btn-primary btn-sm mt-3" @click="saveOverride">保存修正</button>
        </div>

        <div class="card card-pad">
          <h3 class="mb-2 text-sm font-medium text-white">导入历史消息</h3>
          <textarea v-model="raw" rows="6" class="input" placeholder="按行粘贴你自己以前发过的话，一行一条"></textarea>
          <button class="btn-primary btn-sm mt-2" :disabled="busy" @click="importText">导入并重建风格</button>
        </div>
      </div>
    </div>
    <div v-else class="text-sm text-slate-500">先选一个账号</div>
  </div>
</template>
