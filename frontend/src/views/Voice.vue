<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../lib/api'
import { LANGS, ui } from '../lib/store'

const catalog = ref({})
const lang = ref('zh-CN')
const gender = ref('female')
const text = ref('刚下班，今天有点累，你在干嘛呢')
const rate = ref(1)
const pitch = ref(1)
const playing = ref('')
const audio = ref(null)
const assets = ref([])
const uploading = ref(false)
const cloneName = ref('我的音色')

const voices = computed(() => catalog.value[lang.value]?.[gender.value] || [])

async function load() {
  try {
    catalog.value = await api.get('/api/voice/catalog')
    assets.value = await api.get('/api/voice/assets')
  } catch (e) { ui.err(e.message) }
}

async function preview(v) {
  if (playing.value) return
  playing.value = v.id
  try {
    const r = await api.post('/api/voice/preview', {
      text: text.value, lang: lang.value, gender: gender.value,
      voice: v.provider === 'clone' ? '' : v.id, rate: Number(rate.value), pitch: Number(pitch.value),
    })
    if (audio.value) { audio.value.pause() }
    audio.value = new Audio(r.url)
    await audio.value.play()
    ui.ok(`已生成 ${r.duration}s 语音条（ogg/opus）`)
  } catch (e) { ui.err(e.message) } finally { playing.value = '' }
}

async function upload(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  uploading.value = true
  try {
    const r = await api.upload(`/api/voice/clone?name=${encodeURIComponent(cloneName.value)}`, fd)
    ui.ok(`克隆完成，voice_id: ${r.voice_id}`)
    load()
  } catch (err) { ui.err(err.message) } finally { uploading.value = false; e.target.value = '' }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="card card-pad">
      <h3 class="mb-3 text-sm font-medium text-white">试听与生成</h3>
      <div class="grid gap-3 md:grid-cols-4">
        <div>
          <label class="label">语言</label>
          <select v-model="lang" class="input">
            <option v-for="l in LANGS" :key="l.v" :value="l.v">{{ l.label }}</option>
          </select>
        </div>
        <div>
          <label class="label">性别</label>
          <select v-model="gender" class="input"><option value="female">女声</option><option value="male">男声</option></select>
        </div>
        <div><label class="label">语速</label><input v-model.number="rate" step="0.05" type="number" class="input" /></div>
        <div><label class="label">音调</label><input v-model.number="pitch" step="0.05" type="number" class="input" /></div>
      </div>
      <div class="mt-3"><label class="label">试听文本</label><input v-model="text" class="input" /></div>
      <p class="mt-2 text-[11px] text-slate-500">输出统一为 ogg / opus / 单声道 / 48kHz，以语音条形式发送（不是音频文件）。</p>
    </div>

    <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <div v-for="v in voices" :key="v.id + v.name" class="card card-pad">
        <div class="flex items-start justify-between">
          <div>
            <div class="text-sm text-slate-100">{{ v.name }}</div>
            <div class="mono text-[10px] text-slate-600">{{ v.id }}</div>
          </div>
          <span class="badge" :class="v.provider === 'clone' ? 'bg-warn/15 text-warn' : 'bg-accent/10 text-accent'">{{ v.provider }}</span>
        </div>
        <button class="btn-ghost btn-sm mt-3 w-full" :disabled="playing === v.id" @click="preview(v)">
          {{ playing === v.id ? '生成中…' : '▶ 试听这条' }}
        </button>
      </div>
      <div v-if="!voices.length" class="card card-pad text-xs text-slate-500">这个语言/性别暂时没有可用音色，可以上传样本克隆一个。</div>
    </div>

    <div class="card card-pad">
      <h3 class="mb-3 text-sm font-medium text-white">少样本克隆（30 秒 – 3 分钟）</h3>
      <div class="flex flex-wrap items-end gap-3">
        <div><label class="label">音色名称</label><input v-model="cloneName" class="input" /></div>
        <div>
          <label class="label">样本文件（mp3/wav/m4a）</label>
          <input type="file" accept="audio/*" class="input" @change="upload" :disabled="uploading" />
        </div>
      </div>
      <p v-if="uploading" class="mt-2 text-xs text-accent">上传中…</p>
      <p class="mt-2 text-[11px] text-slate-500">克隆需要配置克隆服务（TTS_CLONE_BASE_URL / TTS_CLONE_API_KEY）。没配置时先用内置音色。</p>

      <div v-if="assets.length" class="mt-4 space-y-1.5">
        <div class="text-[11px] text-slate-500">我的音色</div>
        <div v-for="a in assets" :key="a.id" class="flex items-center justify-between rounded border border-line/70 px-2.5 py-1.5 text-xs">
          <span class="text-slate-300">{{ a.name }} <span class="mono text-slate-600">{{ a.voice_id }}</span></span>
          <span class="badge" :class="a.is_clone ? 'bg-warn/15 text-warn' : 'bg-slate-700/40 text-slate-400'">{{ a.is_clone ? '克隆' : a.provider }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
