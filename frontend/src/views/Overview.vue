<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { fmtNum, fmtTime, ui } from '../lib/store'

const data = ref(null)
const accounts = ref([])
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    data.value = await api.get('/api/stats/overview')
    accounts.value = await api.get('/api/accounts')
  } catch (e) { ui.err(e.message) } finally { loading.value = false }
}

const kpis = () => [
  { label: '账号在线', value: `${data.value.accounts_online}/${data.value.accounts_total}`, sub: `AI 开启 ${data.value.accounts_ai_on}` },
  { label: '联系人', value: fmtNum(data.value.contacts_total), sub: '独立记忆隔离' },
  { label: '今日消息', value: fmtNum(data.value.messages_today), sub: `发出 ${data.value.out_today} 条` },
  { label: '今日语音条', value: fmtNum(data.value.voice_today), sub: 'ogg / opus / 48k' },
]

const maxTrend = () => Math.max(1, ...(data.value?.trend || []).map((t) => t.count))

onMounted(load)
</script>

<template>
  <div v-if="loading" class="text-sm text-slate-500">加载中…</div>
  <div v-else-if="data" class="space-y-5">
    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <div v-for="k in kpis()" :key="k.label" class="card card-pad">
        <div class="text-[11px] uppercase tracking-wider text-slate-500">{{ k.label }}</div>
        <div class="mt-1.5 text-2xl font-semibold text-white">{{ k.value }}</div>
        <div class="mt-0.5 text-[11px] text-slate-500">{{ k.sub }}</div>
      </div>
    </div>

    <div class="grid gap-4 lg:grid-cols-3">
      <div class="card card-pad lg:col-span-2">
        <div class="mb-4 flex items-center justify-between">
          <h2 class="text-sm font-medium text-white">近 7 日消息量</h2>
          <span class="mono text-[11px] text-slate-500">token 7d: {{ fmtNum(data.usage_7d.prompt_tokens + data.usage_7d.completion_tokens) }}</span>
        </div>
        <div class="flex h-40 items-end gap-2">
          <div v-for="t in data.trend" :key="t.date" class="flex flex-1 flex-col items-center gap-1.5">
            <div class="text-[10px] text-slate-500">{{ t.count }}</div>
            <div class="w-full rounded-t bg-gradient-to-t from-accent-dim to-accent/70"
                 :style="{ height: `${Math.max(4, (t.count / maxTrend()) * 110)}px` }"></div>
            <div class="mono text-[10px] text-slate-600">{{ t.date }}</div>
          </div>
        </div>
      </div>

      <div class="card card-pad">
        <h2 class="mb-3 text-sm font-medium text-white">账号状态</h2>
        <div v-if="!accounts.length" class="text-xs text-slate-500">还没有接入账号</div>
        <div v-for="a in accounts" :key="a.id" class="mb-2 flex items-center justify-between rounded-lg border border-line/70 px-2.5 py-2">
          <div class="min-w-0">
            <div class="truncate text-sm text-slate-200">{{ a.label }}</div>
            <div class="mono text-[10px] text-slate-600">{{ a.phone }}</div>
          </div>
          <span class="badge" :class="a.live_status === 'online' ? 'bg-ok/15 text-ok' : 'bg-slate-700/40 text-slate-400'">
            {{ a.live_status === 'online' ? '在线' : a.live_status }}
          </span>
        </div>
        <router-link to="/accounts" class="mt-3 block text-center text-xs link">管理账号 →</router-link>
      </div>
    </div>

    <div class="grid gap-4 lg:grid-cols-2">
      <div class="card card-pad">
        <h2 class="mb-3 text-sm font-medium text-white">最近操作审计</h2>
        <div v-if="!data.recent_audit.length" class="text-xs text-slate-500">暂无记录</div>
        <div v-for="a in data.recent_audit" :key="a.id" class="flex items-center justify-between border-t border-line/60 py-2 text-xs first:border-0">
          <span class="text-slate-300">{{ a.action }}</span>
          <span class="text-slate-500">{{ a.actor }} · {{ fmtTime(a.created_at) }}</span>
        </div>
        <router-link to="/logs" class="mt-2 block text-xs link">查看全部 →</router-link>
      </div>

      <div class="card card-pad">
        <h2 class="mb-3 text-sm font-medium text-white">快速开始</h2>
        <ol class="space-y-2 text-xs text-slate-400">
          <li>1. 在「系统设置」填模型地址与 Key，点测试连通</li>
          <li>2. 在「账户管理」添加手机号 → 收验证码登录（会话加密持久化）</li>
          <li>3. 在「人设管理」选模板或自定义，绑定到账号</li>
          <li>4. 「风格档案」拉取本人历史消息，生成说话风格</li>
          <li>5. 「主动任务」筛选联系人、设时段与频率，先看预热期额度</li>
        </ol>
        <div class="mt-3 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-[11px] text-warn">
          新号前 36 小时只做被动回复，不主动找人。这是硬限制，防止刚登录就被封。
        </div>
      </div>
    </div>
  </div>
</template>
