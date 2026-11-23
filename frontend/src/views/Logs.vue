<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { fmtNum, fmtTime, ui } from '../lib/store'

const tab = ref('audit')
const audit = ref({ total: 0, items: [] })
const usage = ref([])
const control = ref([])
const page = ref(1)
const action = ref('')

async function load() {
  try {
    if (tab.value === 'audit') {
      audit.value = await api.get(`/api/logs/audit?page=${page.value}&size=50&action=${encodeURIComponent(action.value)}`)
    } else if (tab.value === 'usage') {
      usage.value = await api.get(`/api/logs/usage?page=${page.value}&size=50`)
    } else {
      control.value = await api.get('/api/logs/control')
    }
  } catch (e) { ui.err(e.message) }
}

function switchTab(t) { tab.value = t; page.value = 1; load() }
onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <button v-for="t in [{k:'audit',n:'操作审计'},{k:'usage',n:'模型用量'},{k:'control',n:'控制指令'}]" :key="t.k"
              class="btn-sm rounded-lg px-3 py-1.5"
              :class="tab === t.k ? 'bg-accent text-ink-950' : 'border border-line bg-ink-800 text-slate-300'"
              @click="switchTab(t.k)">{{ t.n }}</button>
      <input v-if="tab === 'audit'" v-model="action" class="input max-w-[200px]" placeholder="按动作过滤" @keyup.enter="load" />
      <button class="btn-ghost btn-sm" @click="load">刷新</button>
    </div>

    <div v-if="tab === 'audit'" class="card overflow-x-auto">
      <table class="w-full min-w-[760px]">
        <thead><tr><th class="th">时间</th><th class="th">操作人</th><th class="th">动作</th><th class="th">对象</th><th class="th">详情</th><th class="th">IP</th></tr></thead>
        <tbody>
          <tr v-for="a in audit.items" :key="a.id" class="row">
            <td class="td text-xs text-slate-500">{{ fmtTime(a.created_at) }}</td>
            <td class="td text-xs">{{ a.actor }}</td>
            <td class="td"><span class="badge bg-ink-700 text-slate-300">{{ a.action }}</span></td>
            <td class="td mono text-[11px] text-slate-500">{{ a.object_type }} {{ a.object_id }}</td>
            <td class="td mono text-[10px] text-slate-500 max-w-[260px] truncate">{{ JSON.stringify(a.detail) }}</td>
            <td class="td mono text-[10px] text-slate-600">{{ a.ip || '—' }}</td>
          </tr>
          <tr v-if="!audit.items.length"><td class="td text-slate-500" colspan="6">暂无记录</td></tr>
        </tbody>
      </table>
      <div class="flex items-center justify-between border-t border-line px-3 py-2 text-xs text-slate-500">
        <span>共 {{ audit.total }} 条</span>
        <div class="flex gap-2">
          <button class="btn-ghost btn-sm" :disabled="page <= 1" @click="page--; load()">上一页</button>
          <button class="btn-ghost btn-sm" @click="page++; load()">下一页</button>
        </div>
      </div>
    </div>

    <div v-else-if="tab === 'usage'" class="card overflow-x-auto">
      <table class="w-full min-w-[760px]">
        <thead><tr><th class="th">时间</th><th class="th">类型</th><th class="th">模型</th><th class="th">输入 token</th><th class="th">输出 token</th><th class="th">字符</th><th class="th">耗时</th><th class="th">状态</th></tr></thead>
        <tbody>
          <tr v-for="u in usage" :key="u.id" class="row">
            <td class="td text-xs text-slate-500">{{ fmtTime(u.created_at) }}</td>
            <td class="td"><span class="badge bg-ink-700 text-slate-300">{{ u.kind }}</span></td>
            <td class="td mono text-[11px]">{{ u.model || '—' }}</td>
            <td class="td mono">{{ fmtNum(u.prompt_tokens) }}</td>
            <td class="td mono">{{ fmtNum(u.completion_tokens) }}</td>
            <td class="td mono">{{ fmtNum(u.chars) }}</td>
            <td class="td mono text-[11px]">{{ u.elapsed_ms }}ms</td>
            <td class="td">
              <span class="badge" :class="u.ok ? 'bg-ok/15 text-ok' : 'bg-danger/15 text-danger'">{{ u.ok ? 'OK' : '失败' }}</span>
              <div v-if="u.error" class="mt-0.5 text-[10px] text-danger">{{ u.error }}</div>
            </td>
          </tr>
          <tr v-if="!usage.length"><td class="td text-slate-500" colspan="8">暂无记录</td></tr>
        </tbody>
      </table>
    </div>

    <div v-else class="card overflow-x-auto">
      <table class="w-full min-w-[600px]">
        <thead><tr><th class="th">时间</th><th class="th">来源</th><th class="th">指令</th><th class="th">目标</th><th class="th">结果</th></tr></thead>
        <tbody>
          <tr v-for="c in control" :key="c.id" class="row">
            <td class="td text-xs text-slate-500">{{ fmtTime(c.created_at) }}</td>
            <td class="td text-xs">{{ c.source }}</td>
            <td class="td mono">{{ c.command }}</td>
            <td class="td text-xs">{{ c.target || '—' }}</td>
            <td class="td text-xs text-slate-400">{{ c.result }}</td>
          </tr>
          <tr v-if="!control.length"><td class="td text-slate-500" colspan="5">暂无记录</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
