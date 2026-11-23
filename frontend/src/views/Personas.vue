<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../lib/api'
import { LANGS, ui } from '../lib/store'

const list = ref([])
const accounts = ref([])
const rules = ref([])
const editing = ref(null)
const showRule = ref(false)
const ruleForm = reactive({ account_id: null, persona_id: null, contact_id: null, time_start: '00:00', time_end: '23:59', priority: 10 })

const blank = () => ({
  name: '新人设', gender: 'female', age: 26, job: '', city: '', timezone: 'Asia/Phnom_Penh',
  traits: [], tone_level: 3, catchphrases: [], emoji_habit: '偶尔', sentence_len: '短句',
  paragraph_habit: '拆条', taboo_topics: [], intimacy_default: 40, default_language: 'zh-CN',
  voice_id: '', voice_ratio: 20, voice_rate: 1, voice_pitch: 1,
  active_hours: { start: '09:00', end: '23:30' }, background: '', is_template: false,
})

async function load() {
  try {
    list.value = await api.get('/api/personas')
    accounts.value = await api.get('/api/accounts')
    rules.value = await api.get('/api/personas/rules/list')
  } catch (e) { ui.err(e.message) }
}

function edit(p) {
  editing.value = JSON.parse(JSON.stringify(p || blank()))
}
function arr(v) { return (v || '').split(/[,，\n]/).map((s) => s.trim()).filter(Boolean) }

async function save() {
  const p = editing.value
  const payload = { ...p, traits: Array.isArray(p.traits) ? p.traits : arr(p.traits), catchphrases: Array.isArray(p.catchphrases) ? p.catchphrases : arr(p.catchphrases), taboo_topics: Array.isArray(p.taboo_topics) ? p.taboo_topics : arr(p.taboo_topics) }
  ;['id', 'is_template', 'created_at', 'updated_at', 'bound_accounts'].forEach((k) => delete payload[k])
  try {
    if (p.id) await api.patch(`/api/personas/${p.id}`, payload)
    else await api.post('/api/personas', payload)
    ui.ok('已保存')
    editing.value = null
    load()
  } catch (e) { ui.err(e.message) }
}

async function clone(p) {
  try { await api.post(`/api/personas/${p.id}/copy`, {}); ui.ok('已复制'); load() } catch (e) { ui.err(e.message) }
}
async function remove(p) {
  if (!confirm(`删除人设「${p.name}」？`)) return
  try { await api.del(`/api/personas/${p.id}`); load() } catch (e) { ui.err(e.message) }
}
async function bind(p) {
  const acc = accounts.value[0]
  if (!acc) return ui.err('先添加一个账号')
  try { await api.patch(`/api/accounts/${acc.id}`, { persona_id: p.id }); ui.ok(`已绑定到 ${acc.label}`); load() } catch (e) { ui.err(e.message) }
}
function exportPersona(p) {
  const blob = new Blob([JSON.stringify({ version: 1, persona: p }, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `persona-${p.name}.json`
  a.click()
}
async function addRule() {
  try {
    await api.post('/api/personas/rules', { ...ruleForm, account_id: Number(ruleForm.account_id), persona_id: Number(ruleForm.persona_id) })
    ui.ok('规则已添加')
    showRule.value = false
    load()
  } catch (e) { ui.err(e.message) }
}
async function delRule(r) {
  try { await api.del(`/api/personas/rules/${r.id}`); load() } catch (e) { ui.err(e.message) }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <button class="btn-primary" @click="edit(null)">+ 新建人设</button>
      <button class="btn-ghost" @click="showRule = !showRule">自动切换规则</button>
      <span class="text-[11px] text-slate-500">{{ list.length }} 个人设 · 内置模板可直接复制修改</span>
    </div>

    <div v-if="showRule" class="card card-pad space-y-3">
      <h3 class="text-sm font-medium text-white">按联系人或时段自动切换</h3>
      <div class="grid gap-3 md:grid-cols-5">
        <div><label class="label">账号</label>
          <select v-model="ruleForm.account_id" class="input"><option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.label }}</option></select>
        </div>
        <div><label class="label">人设</label>
          <select v-model="ruleForm.persona_id" class="input"><option v-for="p in list" :key="p.id" :value="p.id">{{ p.name }}</option></select>
        </div>
        <div><label class="label">开始</label><input v-model="ruleForm.time_start" class="input mono" placeholder="09:00" /></div>
        <div><label class="label">结束</label><input v-model="ruleForm.time_end" class="input mono" placeholder="18:00" /></div>
        <div><label class="label">优先级</label><input v-model.number="ruleForm.priority" type="number" class="input" /></div>
      </div>
      <button class="btn-primary btn-sm" @click="addRule">添加规则</button>
      <div v-if="rules.length" class="space-y-1.5 pt-2">
        <div v-for="r in rules" :key="r.id" class="flex items-center justify-between rounded-lg border border-line/70 px-3 py-2 text-xs">
          <span class="text-slate-300">账号 #{{ r.account_id }} → {{ r.persona_name }} · {{ r.time_start }}-{{ r.time_end }} · 优先级 {{ r.priority }}</span>
          <button class="btn-danger btn-sm" @click="delRule(r)">删除</button>
        </div>
      </div>
    </div>

    <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <div v-for="p in list" :key="p.id" class="card card-pad">
        <div class="flex items-start justify-between">
          <div>
            <div class="text-sm font-semibold text-white">{{ p.name }}</div>
            <div class="mt-0.5 text-[11px] text-slate-500">
              {{ p.gender === 'female' ? '女' : '男' }} · {{ p.age }} 岁 · {{ p.job || '—' }} · {{ p.city || '—' }}
            </div>
          </div>
          <span v-if="p.is_template" class="badge bg-accent/15 text-accent">模板</span>
          <span v-else class="badge bg-slate-700/40 text-slate-400">自定义</span>
        </div>
        <p class="mt-2 line-clamp-2 text-xs text-slate-400">{{ p.background || '（无背景设定）' }}</p>
        <div class="mt-2 flex flex-wrap gap-1">
          <span v-for="t in (p.traits || []).slice(0, 4)" :key="t" class="badge bg-ink-700 text-slate-300">{{ t }}</span>
        </div>
        <div class="mt-2 text-[11px] text-slate-500">语气 {{ p.tone_level }}/5 · {{ p.sentence_len }} · {{ p.paragraph_habit }} · 语音 {{ p.voice_ratio }}%</div>
        <div class="mt-3 flex flex-wrap gap-1.5">
          <button class="btn-ghost btn-sm" @click="edit(p)">编辑</button>
          <button class="btn-ghost btn-sm" @click="clone(p)">复制</button>
          <button class="btn-ghost btn-sm" @click="exportPersona(p)">导出</button>
          <button class="btn-ghost btn-sm" @click="bind(p)">绑账号</button>
          <button v-if="!p.is_template" class="btn-danger btn-sm" @click="remove(p)">删除</button>
        </div>
      </div>
    </div>

    <!-- 编辑面板 -->
    <div v-if="editing" class="fixed inset-0 z-50 overflow-y-auto bg-black/70 p-4">
      <div class="card mx-auto my-6 max-w-3xl card-pad">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-base font-semibold text-white">{{ editing.id ? '编辑人设' : '新建人设' }}</h3>
          <button class="btn-ghost btn-sm" @click="editing = null">关闭</button>
        </div>
        <div class="grid gap-3 md:grid-cols-3">
          <div><label class="label">姓名</label><input v-model="editing.name" class="input" /></div>
          <div><label class="label">性别</label>
            <select v-model="editing.gender" class="input"><option value="female">女</option><option value="male">男</option></select>
          </div>
          <div><label class="label">年龄</label><input v-model.number="editing.age" type="number" class="input" /></div>
          <div><label class="label">职业</label><input v-model="editing.job" class="input" /></div>
          <div><label class="label">城市</label><input v-model="editing.city" class="input" /></div>
          <div><label class="label">时区</label><input v-model="editing.timezone" class="input mono" /></div>
          <div class="md:col-span-3"><label class="label">性格关键词（逗号分隔）</label><input :value="(editing.traits || []).join('，')" class="input" @input="editing.traits = $event.target.value" /></div>
          <div><label class="label">语气浓度 1-5</label><input v-model.number="editing.tone_level" type="number" min="1" max="5" class="input" /></div>
          <div><label class="label">句长偏好</label>
            <select v-model="editing.sentence_len" class="input"><option>短句</option><option>中等</option><option>长句</option></select>
          </div>
          <div><label class="label">分段习惯</label>
            <select v-model="editing.paragraph_habit" class="input"><option>拆条</option><option>整条</option></select>
          </div>
          <div><label class="label">口头禅（逗号分隔）</label><input :value="(editing.catchphrases || []).join('，')" class="input" @input="editing.catchphrases = $event.target.value" /></div>
          <div><label class="label">emoji 习惯</label>
            <select v-model="editing.emoji_habit" class="input"><option>很少</option><option>偶尔</option><option>很多</option></select>
          </div>
          <div><label class="label">默认语言</label>
            <select v-model="editing.default_language" class="input"><option v-for="l in LANGS" :key="l.v" :value="l.v">{{ l.label }}</option></select>
          </div>
          <div class="md:col-span-3"><label class="label">禁忌话题（逗号分隔）</label><input :value="(editing.taboo_topics || []).join('，')" class="input" @input="editing.taboo_topics = $event.target.value" /></div>
          <div><label class="label">默认亲密度</label><input v-model.number="editing.intimacy_default" type="number" class="input" /></div>
          <div><label class="label">语音发送比例 %</label><input v-model.number="editing.voice_ratio" type="number" class="input" /></div>
          <div><label class="label">音色 ID</label><input v-model="editing.voice_id" class="input mono" placeholder="留空用默认音色" /></div>
          <div><label class="label">语速</label><input v-model.number="editing.voice_rate" step="0.05" type="number" class="input" /></div>
          <div><label class="label">音调</label><input v-model.number="editing.voice_pitch" step="0.05" type="number" class="input" /></div>
          <div class="grid grid-cols-2 gap-2">
            <div><label class="label">活跃起</label><input v-model="editing.active_hours.start" class="input mono" /></div>
            <div><label class="label">活跃止</label><input v-model="editing.active_hours.end" class="input mono" /></div>
          </div>
          <div class="md:col-span-3"><label class="label">背景设定</label><textarea v-model="editing.background" rows="3" class="input"></textarea></div>
        </div>
        <div class="mt-4 flex gap-2">
          <button class="btn-primary" @click="save">保存</button>
          <button class="btn-ghost" @click="editing = null">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>
