<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../lib/api'
import { fmtTime, ui } from '../lib/store'

const tasks = ref([])
const accounts = ref([])
const personas = ref([])
const showNew = ref(false)
const preview = ref(null)
const targets = ref(null)
const form = reactive({
  account_id: null, name: '新任务', goal: '', persona_id: null,
  window_start: '10:00', window_end: '21:00', daily_limit: 5,
  interval_min: 180, interval_max: 600, tags: '', last_active_days: 0, limit: 50,
})

async function load() {
  try {
    tasks.value = await api.get('/api/proactive/tasks')
    accounts.value = await api.get('/api/accounts')
    personas.value = await api.get('/api/personas')
  } catch (e) { ui.err(e.message) }
}

async function create() {
  if (!form.account_id) return ui.err('先选账号')
  try {
    await api.post('/api/proactive/tasks', {
      account_id: Number(form.account_id), name: form.name, goal: form.goal,
      persona_id: form.persona_id ? Number(form.persona_id) : null,
      filters: {
        tags: form.tags ? form.tags.split(/[,，]/).map((s) => s.trim()).filter(Boolean) : [],
        last_active_days: Number(form.last_active_days), limit: Number(form.limit),
      },
      window_start: form.window_start, window_end: form.window_end,
      daily_limit: Number(form.daily_limit), interval_min: Number(form.interval_min),
      interval_max: Number(form.interval_max), status: 'paused',
    })
    ui.ok('任务已创建（暂停状态）')
    showNew.value = false
    load()
  } catch (e) { ui.err(e.message) }
}

async function doPreview(t) {
  try { preview.value = { task: t, ...(await api.post(`/api/proactive/tasks/${t.id}/preview`, {})) } } catch (e) { ui.err(e.message) }
}
async function build(t) {
  try {
    const r = await api.post(`/api/proactive/tasks/${t.id}/build`, {})
    ui.ok(`已加入队列 ${r.added} 人`)
    load()
  } catch (e) { ui.err(e.message) }
}
async function toggle(t) {
  try {
    const act = t.status === 'active' ? 'pause' : 'start'
    await api.post(`/api/proactive/tasks/${t.id}/${act}`, {})
    ui.ok(act === 'start' ? '已启动，按额度自动发送' : '已暂停')
    load()
  } catch (e) { ui.err(e.message) }
}
async function runOnce(t) {
  try { await api.post(`/api/proactive/tasks/${t.id}/run_once`, {}); ui.ok('已触发一条，稍后看目标列表') } catch (e) { ui.err(e.message) }
}
async function viewTargets(t) {
  try { targets.value = { task: t, items: await api.get(`/api/proactive/tasks/${t.id}/targets`) } } catch (e) { ui.err(e.message) }
}
async function remove(t) {
  if (!confirm(`删除任务「${t.name}」？`)) return
  try { await api.del(`/api/proactive/tasks/${t.id}`); load() } catch (e) { ui.err(e.message) }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <button class="btn-primary" @click="showNew = !showNew">+ 新建主动任务</button>
      <span class="text-[11px] text-slate-500">新号 36 小时静默，之后每周放量；批次开场白强制互不相同</span>
    </div>

    <div v-if="showNew" class="card card-pad grid gap-3 md:grid-cols-4">
      <div><label class="label">账号</label>
        <select v-model="form.account_id" class="input"><option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.label }}</option></select>
      </div>
      <div><label class="label">任务名</label><input v-model="form.name" class="input" /></div>
      <div><label class="label">人设</label>
        <select v-model="form.persona_id" class="input"><option :value="null">跟随账号</option><option v-for="p in personas" :key="p.id" :value="p.id">{{ p.name }}</option></select>
      </div>
      <div><label class="label">目标（开场白方向）</label><input v-model="form.goal" class="input" placeholder="比如：问问最近生意怎么样" /></div>
      <div><label class="label">发送时段起</label><input v-model="form.window_start" class="input mono" /></div>
      <div><label class="label">发送时段止</label><input v-model="form.window_end" class="input mono" /></div>
      <div><label class="label">每天人数</label><input v-model.number="form.daily_limit" type="number" class="input" /></div>
      <div><label class="label">筛选标签（逗号）</label><input v-model="form.tags" class="input" /></div>
      <div><label class="label">最近互动天数（0=不限）</label><input v-model.number="form.last_active_days" type="number" class="input" /></div>
      <div><label class="label">候选人上限</label><input v-model.number="form.limit" type="number" class="input" /></div>
      <div><label class="label">间隔最小（秒）</label><input v-model.number="form.interval_min" type="number" class="input" /></div>
      <div><label class="label">间隔最大（秒）</label><input v-model.number="form.interval_max" type="number" class="input" /></div>
      <div class="md:col-span-4"><button class="btn-primary" @click="create">创建</button></div>
    </div>

    <div class="card overflow-x-auto">
      <table class="w-full min-w-[900px]">
        <thead><tr>
          <th class="th">任务</th><th class="th">时段 / 额度</th><th class="th">队列</th>
          <th class="th">状态</th><th class="th">上次执行</th><th class="th">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.id" class="row">
            <td class="td">
              <div class="font-medium text-slate-100">{{ t.name }}</div>
              <div class="text-[11px] text-slate-500">{{ t.goal || '（无指定目标）' }}</div>
            </td>
            <td class="td text-xs">
              {{ t.window_start }}–{{ t.window_end }}<br />
              <span class="text-slate-500">每天 {{ t.daily_limit }} · 间隔 {{ t.interval_min }}–{{ t.interval_max }}s</span>
            </td>
            <td class="td mono text-[11px]">
              待发 {{ t.counts.pending }} · 已发 {{ t.counts.sent }}<br />
              <span class="text-slate-600">失败 {{ t.counts.failed }}</span>
            </td>
            <td class="td">
              <span class="badge" :class="t.status === 'active' ? 'bg-ok/15 text-ok' : 'bg-slate-700/40 text-slate-400'">
                {{ t.status === 'active' ? '运行中' : '暂停' }}
              </span>
            </td>
            <td class="td text-xs text-slate-500">{{ fmtTime(t.last_run_at) }}</td>
            <td class="td">
              <div class="flex flex-wrap gap-1">
                <button class="btn-ghost btn-sm" @click="toggle(t)">{{ t.status === 'active' ? '暂停' : '启动' }}</button>
                <button class="btn-ghost btn-sm" @click="doPreview(t)">预览候选</button>
                <button class="btn-ghost btn-sm" @click="build(t)">入队</button>
                <button class="btn-ghost btn-sm" @click="runOnce(t)">试一条</button>
                <button class="btn-ghost btn-sm" @click="viewTargets(t)">目标</button>
                <button class="btn-danger btn-sm" @click="remove(t)">删除</button>
              </div>
            </td>
          </tr>
          <tr v-if="!tasks.length"><td class="td text-slate-500" colspan="6">还没有主动任务。</td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="preview" class="card card-pad">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-sm font-medium text-white">候选对象（{{ preview.count }}）</h3>
        <button class="btn-ghost btn-sm" @click="preview = null">关闭</button>
      </div>
      <div class="max-h-64 space-y-1 overflow-y-auto text-xs">
        <div v-for="i in preview.items" :key="i.contact_id" class="flex justify-between rounded border border-line/60 px-2.5 py-1.5">
          <span class="text-slate-300">{{ i.name }} <span class="text-slate-600">{{ i.username ? '@' + i.username : '' }}</span></span>
          <span class="text-slate-500">{{ i.already_in_task ? '已在队列' : fmtTime(i.last_msg_at) }}</span>
        </div>
        <div v-if="!preview.items.length" class="text-slate-600">没有符合条件的联系人</div>
      </div>
    </div>

    <div v-if="targets" class="card card-pad">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-sm font-medium text-white">目标列表：{{ targets.task.name }}</h3>
        <button class="btn-ghost btn-sm" @click="targets = null">关闭</button>
      </div>
      <div class="max-h-72 space-y-1 overflow-y-auto text-xs">
        <div v-for="t in targets.items" :key="t.id" class="rounded border border-line/60 px-2.5 py-2">
          <div class="flex justify-between">
            <span class="text-slate-300">{{ t.name }} <span class="text-slate-600">@{{ t.username }}</span></span>
            <span class="badge" :class="t.status === 'sent' ? 'bg-ok/15 text-ok' : t.status === 'failed' ? 'bg-danger/15 text-danger' : 'bg-slate-700/40 text-slate-400'">{{ t.status }}</span>
          </div>
          <div v-if="t.opening" class="mt-1 text-slate-400">「{{ t.opening }}」</div>
          <div v-if="t.error" class="mt-1 text-danger">{{ t.error }}</div>
        </div>
        <div v-if="!targets.items.length" class="text-slate-600">队列为空，先点「入队」</div>
      </div>
    </div>
  </div>
</template>
