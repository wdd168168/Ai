<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../lib/api'
import { fmtTime, ui } from '../lib/store'

const accounts = ref([])
const personas = ref([])
const showAdd = ref(false)
const loginState = reactive({ open: false, account: null, step: 'code', code: '', password: '', hint: '', busy: false })
const form = reactive({
  label: '', phone: '', persona_id: null, api_id: '', api_hash: '',
  device_model: 'Samsung SM-G998B', system_version: 'SDK 33', app_version: '10.9.1 (4874)',
  proxy_scheme: '', proxy_host: '', proxy_port: '', proxy_user: '', proxy_pass: '', proxy_secret: '',
})

async function load() {
  try {
    accounts.value = await api.get('/api/accounts')
    personas.value = await api.get('/api/personas')
  } catch (e) { ui.err(e.message) }
}

function proxyPayload() {
  if (!form.proxy_host) return {}
  return {
    scheme: form.proxy_scheme || 'socks5', host: form.proxy_host, port: Number(form.proxy_port || 1080),
    user: form.proxy_user, pass: form.proxy_pass, secret: form.proxy_secret,
  }
}

async function create() {
  if (!form.phone.trim()) return ui.err('手机号必填（带国家码，如 +855...）')
  try {
    await api.post('/api/accounts', {
      label: form.label || form.phone, phone: form.phone.trim(), persona_id: form.persona_id || null,
      api_id: form.api_id, api_hash: form.api_hash, device_model: form.device_model,
      system_version: form.system_version, app_version: form.app_version, proxy: proxyPayload(),
    })
    showAdd.value = false
    ui.ok('账号已添加，接下来登录')
    await load()
  } catch (e) { ui.err(e.message) }
}

async function startLogin(a) {
  loginState.open = true
  loginState.account = a
  loginState.step = 'code'
  loginState.code = ''
  loginState.password = ''
  loginState.hint = '正在请求验证码…'
  loginState.busy = true
  try {
    const r = await api.post(`/api/accounts/${a.id}/login/send_code`, {})
    loginState.hint = r.hint
  } catch (e) { loginState.hint = e.message }
  finally { loginState.busy = false }
}

async function submitCode() {
  loginState.busy = true
  try {
    const r = await api.post(`/api/accounts/${loginState.account.id}/login/verify`, {
      code: loginState.code.trim(), password: loginState.password,
    })
    if (r.need_password) {
      loginState.step = 'password'
      loginState.hint = r.hint
    } else {
      ui.ok(`登录成功：${r.self_name || ''}`)
      loginState.open = false
      await load()
    }
  } catch (e) { ui.err(e.message) }
  finally { loginState.busy = false }
}

async function toggle(a, field) {
  try {
    await api.patch(`/api/accounts/${a.id}`, { [field]: !a[field] })
    await load()
  } catch (e) { ui.err(e.message) }
}

async function power(a, action) {
  try {
    await api.post(`/api/accounts/${a.id}/${action}`, {})
    ui.ok(action === 'start' ? '已启动' : '已停止')
    setTimeout(load, 1200)
  } catch (e) { ui.err(e.message) }
}

async function remove(a) {
  if (!confirm(`删除账号 ${a.label}？会话与配置一起删掉，不可恢复。`)) return
  try {
    await api.del(`/api/accounts/${a.id}`)
    ui.ok('已删除')
    load()
  } catch (e) { ui.err(e.message) }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <button class="btn-primary" @click="showAdd = !showAdd">+ 添加账号</button>
      <span class="text-[11px] text-slate-500">一号一会话、一出口；会话加密存库，重启免登录</span>
    </div>

    <div v-if="showAdd" class="card card-pad grid gap-3 md:grid-cols-3">
      <div><label class="label">备注名</label><input v-model="form.label" class="input" placeholder="主号 / 客服号" /></div>
      <div><label class="label">手机号（含国家码）</label><input v-model="form.phone" class="input" placeholder="+85512345678" /></div>
      <div>
        <label class="label">绑定人设</label>
        <select v-model="form.persona_id" class="input">
          <option :value="null">稍后设置</option>
          <option v-for="p in personas" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>
      <div><label class="label">api_id（留空用平台配置）</label><input v-model="form.api_id" class="input mono" /></div>
      <div><label class="label">api_hash</label><input v-model="form.api_hash" class="input mono" /></div>
      <div>
        <label class="label">设备型号（指纹稳定）</label>
        <input v-model="form.device_model" class="input" />
      </div>
      <div><label class="label">系统版本</label><input v-model="form.system_version" class="input" /></div>
      <div><label class="label">客户端版本</label><input v-model="form.app_version" class="input" /></div>
      <div>
        <label class="label">代理类型</label>
        <select v-model="form.proxy_scheme" class="input">
          <option value="">不用代理</option>
          <option value="socks5">SOCKS5</option>
          <option value="http">HTTP</option>
          <option value="mtproxy">MTProxy</option>
        </select>
      </div>
      <div><label class="label">代理地址</label><input v-model="form.proxy_host" class="input mono" placeholder="1.2.3.4" /></div>
      <div><label class="label">端口</label><input v-model="form.proxy_port" class="input mono" placeholder="1080" /></div>
      <div v-if="form.proxy_scheme === 'mtproxy'"><label class="label">MTProxy secret</label><input v-model="form.proxy_secret" class="input mono" /></div>
      <template v-else>
        <div><label class="label">代理用户名</label><input v-model="form.proxy_user" class="input" /></div>
        <div><label class="label">代理密码</label><input v-model="form.proxy_pass" class="input" type="password" /></div>
      </template>
      <div class="md:col-span-3 flex gap-2">
        <button class="btn-primary" @click="create">保存</button>
        <button class="btn-ghost" @click="showAdd = false">取消</button>
      </div>
    </div>

    <div class="card overflow-x-auto">
      <table class="w-full min-w-[900px]">
        <thead><tr>
          <th class="th">账号</th><th class="th">状态</th><th class="th">人设</th>
          <th class="th">今日发出</th><th class="th">限速 分/时/天</th><th class="th">AI / 自动回复</th><th class="th">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="a in accounts" :key="a.id" class="row">
            <td class="td">
              <div class="font-medium text-slate-100">{{ a.label }}</div>
              <div class="mono text-[11px] text-slate-500">{{ a.phone }}<span v-if="a.tg_self_name"> · {{ a.tg_self_name }}</span></div>
              <div v-if="a.last_error" class="mt-1 text-[11px] text-danger">{{ a.last_error }}</div>
            </td>
            <td class="td">
              <span class="badge" :class="a.live_status === 'online' ? 'bg-ok/15 text-ok' : 'bg-slate-700/40 text-slate-400'">
                {{ a.live_status === 'online' ? '在线' : a.status }}
              </span>
              <div v-if="!a.has_session" class="mt-1 text-[11px] text-warn">未登录</div>
            </td>
            <td class="td text-xs">{{ a.persona_name || '—' }}</td>
            <td class="td mono">{{ a.sent_today }}</td>
            <td class="td mono text-[11px] text-slate-400">
              {{ a.limits_live?.limits?.minute }}/{{ a.limits_live?.limits?.hour }}/{{ a.limits_live?.limits?.day }}
              <div class="text-[10px] text-slate-600">主动额度 {{ a.limits_live?.proactive_cap_today }}</div>
            </td>
            <td class="td">
              <button class="badge mr-1" :class="a.ai_enabled ? 'bg-ok/15 text-ok' : 'bg-slate-700/40 text-slate-400'" @click="toggle(a, 'ai_enabled')">
                AI {{ a.ai_enabled ? '开' : '关' }}
              </button>
              <button class="badge" :class="a.auto_reply ? 'bg-accent/15 text-accent' : 'bg-slate-700/40 text-slate-400'" @click="toggle(a, 'auto_reply')">
                回复 {{ a.auto_reply ? '开' : '关' }}
              </button>
            </td>
            <td class="td">
              <div class="flex flex-wrap gap-1">
                <button v-if="!a.has_session" class="btn-primary btn-sm" @click="startLogin(a)">登录</button>
                <button v-else class="btn-ghost btn-sm" @click="startLogin(a)">重新登录</button>
                <button class="btn-ghost btn-sm" @click="power(a, 'start')">启动</button>
                <button class="btn-ghost btn-sm" @click="power(a, 'stop')">停止</button>
                <button class="btn-danger btn-sm" @click="remove(a)">删除</button>
              </div>
            </td>
          </tr>
          <tr v-if="!accounts.length"><td class="td text-slate-500" colspan="7">还没有账号，点上面「添加账号」开始。</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 登录流程 -->
    <div v-if="loginState.open" class="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4">
      <div class="card card-pad w-full max-w-md">
        <h3 class="mb-1 text-base font-semibold text-white">登录 {{ loginState.account?.label }}</h3>
        <p class="mb-4 text-xs text-slate-400">{{ loginState.hint }}</p>
        <div v-if="loginState.step === 'code'" class="space-y-3">
          <div><label class="label">验证码</label><input v-model="loginState.code" class="input mono" inputmode="numeric" placeholder="12345" /></div>
          <div class="flex gap-2">
            <button class="btn-primary flex-1" :disabled="loginState.busy" @click="submitCode">提交</button>
            <button class="btn-ghost" @click="loginState.open = false">取消</button>
          </div>
        </div>
        <div v-else class="space-y-3">
          <div><label class="label">两步验证密码</label><input v-model="loginState.password" type="password" class="input" /></div>
          <div class="flex gap-2">
            <button class="btn-primary flex-1" :disabled="loginState.busy" @click="submitCode">提交</button>
            <button class="btn-ghost" @click="loginState.open = false">取消</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
