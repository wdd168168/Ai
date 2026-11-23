<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../lib/api'
import { fmtTime, ui } from '../lib/store'

const route = useRoute()
const cid = route.params.id
const messages = ref([])
const detail = ref(null)
const text = ref('')
const busy = ref(false)
const scroller = ref(null)

const aiActive = computed(() => {
  const d = detail.value
  if (!d) return false
  if (d.blacklist) return false
  return d.ai_enabled
})

async function load() {
  try {
    const [msgs, d] = await Promise.all([api.get(`/api/chats/${cid}/messages?limit=60`), api.get(`/api/contacts/${cid}`)])
    messages.value = msgs
    detail.value = d
    await nextTick()
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  } catch (e) { ui.err(e.message) }
}

async function send() {
  const t = text.value.trim()
  if (!t) return
  busy.value = true
  try {
    await api.post(`/api/chats/${cid}/send`, { text: t })
    text.value = ''
    ui.ok('已发出')
    load()
  } catch (e) { ui.err(e.message) } finally { busy.value = false }
}

async function stop() {
  try { await api.post(`/api/chats/${cid}/stop`, {}); ui.ok('AI 已停止接管这个会话'); load() } catch (e) { ui.err(e.message) }
}
async function resume() {
  try { await api.post(`/api/chats/${cid}/resume`, {}); ui.ok('AI 已恢复接管'); load() } catch (e) { ui.err(e.message) }
}
async function clearMemory() {
  if (!confirm('清空这个联系人的全部记忆与对话记录？不可恢复。')) return
  try { await api.del(`/api/chats/${cid}/memory`); ui.ok('已清空'); load() } catch (e) { ui.err(e.message) }
}

onMounted(load)
</script>

<template>
  <div class="grid gap-4 xl:grid-cols-[1fr_320px]">
    <!-- 对话流 -->
    <div class="card flex h-[calc(100vh-9rem)] flex-col">
      <div class="flex items-center gap-2 border-b border-line px-4 py-3">
        <router-link to="/chats" class="text-xs text-slate-500 hover:text-slate-300">← 返回</router-link>
        <div class="ml-2 text-sm font-medium text-white">{{ detail?.name || '会话' }}</div>
        <span v-if="detail?.username" class="mono text-[11px] text-slate-600">@{{ detail.username }}</span>
        <span class="badge ml-1" :class="aiActive ? 'bg-ok/15 text-ok' : 'bg-warn/15 text-warn'">
          {{ aiActive ? 'AI 接管中' : '已暂停' }}
        </span>
        <div class="ml-auto flex gap-1.5">
          <button v-if="aiActive" class="btn-danger btn-sm" @click="stop">一键停</button>
          <button v-else class="btn-ghost btn-sm" @click="resume">恢复接管</button>
          <button class="btn-ghost btn-sm" @click="load">刷新</button>
        </div>
      </div>

      <div ref="scroller" class="flex-1 space-y-3 overflow-y-auto p-4">
        <div v-if="!messages.length" class="mt-10 text-center text-xs text-slate-500">还没有消息记录</div>
        <div v-for="m in messages" :key="m.id" class="flex" :class="m.direction === 'out' ? 'justify-end' : 'justify-start'">
          <div class="max-w-[78%]">
            <div
              class="rounded-2xl px-3.5 py-2 text-sm leading-relaxed"
              :class="m.direction === 'out'
                ? (m.source === 'manual' ? 'bg-ink-600 text-white' : 'bg-accent/15 text-accent-soft border border-accent-dim/40')
                : 'bg-ink-800 text-slate-200'"
            >
              <span v-if="m.msg_type === 'voice'" class="mr-1 text-[11px] opacity-70">♪ 语音条</span>
              {{ m.text }}
            </div>
            <div class="mt-1 flex items-center gap-2 text-[10px] text-slate-600" :class="m.direction === 'out' ? 'justify-end' : ''">
              <span>{{ m.direction === 'out' ? (m.source === 'manual' ? '人工' : 'AI') : '对方' }}</span>
              <span>{{ m.lang }}</span>
              <span>{{ fmtTime(m.created_at) }}</span>
              <span v-if="m.meta?.persona_name">· {{ m.meta.persona_name }}</span>
              <span v-if="m.meta?.typing_seconds">· 打字 {{ m.meta.typing_seconds }}s</span>
            </div>
            <div v-if="m.meta?.memory_used?.length" class="mt-1 text-[10px] text-slate-600">
              依据记忆：{{ m.meta.memory_used.join('；') }}
            </div>
          </div>
        </div>
      </div>

      <div class="border-t border-line p-3">
        <div class="flex gap-2">
          <input v-model="text" class="input" placeholder="人工插话：直接以账号身份发出，AI 会看到这条并继续上下文"
                 @keyup.enter="send" />
          <button class="btn-primary" :disabled="busy" @click="send">发送</button>
        </div>
      </div>
    </div>

    <!-- 画像与记忆 -->
    <div class="space-y-3">
      <div class="card card-pad">
        <h3 class="mb-2 text-sm font-medium text-white">兴趣画像</h3>
        <div v-if="!detail" class="text-xs text-slate-500">加载中…</div>
        <template v-else>
          <div class="mb-2 flex items-center justify-between text-[11px] text-slate-500">
            <span>亲密度</span><span class="mono text-accent">{{ detail.intimacy }}/100</span>
          </div>
          <div class="mb-3 h-1.5 overflow-hidden rounded bg-ink-700">
            <div class="h-full bg-accent" :style="{ width: detail.intimacy + '%' }"></div>
          </div>
          <div class="mb-1.5 text-[11px] text-slate-500">兴趣 TOP5</div>
          <div class="mb-3 flex flex-wrap gap-1">
            <span v-for="i in detail.interests" :key="i.topic" class="badge bg-accent/10 text-accent" :title="i.evidence">
              {{ i.topic }} {{ (i.score * 100).toFixed(0) }}%
            </span>
            <span v-if="!detail.interests?.length" class="text-xs text-slate-600">暂无</span>
          </div>
          <div class="mb-1.5 text-[11px] text-slate-500">情绪基线</div>
          <div class="mb-3 text-xs text-slate-300">{{ detail.emotion_baseline }}</div>
          <div class="mb-1.5 text-[11px] text-slate-500">未完成话题</div>
          <ul class="mb-3 space-y-1 text-xs text-slate-400">
            <li v-for="t in detail.unfinished_topics" :key="t">· {{ t }}</li>
            <li v-if="!detail.unfinished_topics?.length" class="text-slate-600">暂无</li>
          </ul>
          <div class="mb-1.5 text-[11px] text-slate-500">回避话题</div>
          <div class="flex flex-wrap gap-1">
            <span v-for="t in detail.avoid_topics" :key="t" class="badge bg-danger/10 text-danger">{{ t }}</span>
            <span v-if="!detail.avoid_topics?.length" class="text-xs text-slate-600">暂无</span>
          </div>
        </template>
      </div>

      <div class="card card-pad">
        <div class="mb-2 flex items-center justify-between">
          <h3 class="text-sm font-medium text-white">长期记忆</h3>
          <button class="btn-danger btn-sm" @click="clearMemory">清空</button>
        </div>
        <div class="max-h-72 space-y-1.5 overflow-y-auto">
          <div v-for="f in detail?.facts || []" :key="f.id" class="rounded-lg border border-line/70 px-2.5 py-1.5">
            <div class="flex items-center justify-between">
              <span class="badge bg-ink-700 text-slate-400">{{ f.category }}</span>
              <span class="mono text-[10px] text-slate-600">w{{ f.weight }}</span>
            </div>
            <div class="mt-1 text-xs text-slate-300">{{ f.content }}</div>
            <div v-if="f.due_at" class="mt-0.5 text-[10px] text-warn">约定期：{{ f.due_at.slice(0, 10) }}</div>
          </div>
          <div v-if="!(detail?.facts || []).length" class="text-xs text-slate-600">还没有抽取到事实，聊几轮后会自动生成。</div>
        </div>
      </div>
    </div>
  </div>
</template>
