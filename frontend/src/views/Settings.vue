<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api, authApi } from '../lib/api'
import { LANGS, auth, ui } from '../lib/store'

const llm = reactive({ base_url: '', api_key: '', model: '', json_model: '', temperature: 0.9, max_tokens: 700, timeout: 60, api_key_mask: '', api_key_set: false })
const chat = reactive({ lang_mode: 'follow', fixed_lang: 'zh-CN', manual_yield_minutes: 20, reply_in_offhours: false })
const bot = reactive({ token: '', admin_ids: '', token_mask: '', token_set: false })
const pwd = reactive({ old_password: '', new_password: '' })
const twofa = reactive({ secret: '', uri: '', code: '', password: '' })
const testing = ref(false)
const testResult = ref(null)

async function load() {
  try {
    Object.assign(llm, await api.get('/api/settings/llm'))
    Object.assign(chat, await api.get('/api/settings/chat'))
    const b = await api.get('/api/settings/controlbot')
    Object.assign(bot, { token_mask: b.token_mask, token_set: b.token_set, admin_ids: (b.admin_ids || []).join(',') })
    const me = await authApi.me()
    auth.totpEnabled = me.totp_enabled
  } catch (e) { ui.err(e.message) }
}

async function saveLlm() {
  try {
    await api.post('/api/settings/llm', {
      base_url: llm.base_url, api_key: llm.api_key, model: llm.model, json_model: llm.json_model,
      temperature: Number(llm.temperature), max_tokens: Number(llm.max_tokens), timeout: Number(llm.timeout),
    })
    llm.api_key = ''
    ui.ok('模型配置已保存')
    load()
  } catch (e) { ui.err(e.message) }
}

async function testLlm() {
  testing.value = true
  testResult.value = null
  try { testResult.value = await api.post('/api/settings/llm/test', {}) } catch (e) { testResult.value = { ok: false, error: e.message } }
  finally { testing.value = false }
}

async function saveChat() {
  try {
    await api.post('/api/settings/chat', { ...chat, manual_yield_minutes: Number(chat.manual_yield_minutes) })
    ui.ok('聊天策略已保存')
  } catch (e) { ui.err(e.message) }
}

async function saveBot() {
  try {
    await api.post('/api/settings/controlbot', {
      token: bot.token, admin_ids: bot.admin_ids ? bot.admin_ids.split(/[,，]/).map((s) => Number(s.trim())).filter(Boolean) : [],
    })
    bot.token = ''
    ui.ok('控制 bot 配置已保存（重启服务后生效）')
    load()
  } catch (e) { ui.err(e.message) }
}

async function changePwd() {
  try { await authApi.changePassword(pwd.old_password, pwd.new_password); pwd.old_password = ''; pwd.new_password = ''; ui.ok('密码已更新') }
  catch (e) { ui.err(e.message) }
}

async function setup2fa() {
  try { Object.assign(twofa, await authApi.setup2fa()) } catch (e) { ui.err(e.message) }
}
async function enable2fa() {
  try { await authApi.enable2fa(twofa.secret, twofa.code); ui.ok('两步验证已开启'); twofa.secret = ''; load() }
  catch (e) { ui.err(e.message) }
}
async function disable2fa() {
  try { await authApi.disable2fa(twofa.password); ui.ok('两步验证已关闭'); twofa.password = ''; load() }
  catch (e) { ui.err(e.message) }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="card card-pad">
      <div class="mb-3 flex items-center justify-between">
        <h3 class="text-sm font-medium text-white">模型配置（OpenAI 兼容，随便换厂商）</h3>
        <span class="badge" :class="llm.api_key_set ? 'bg-ok/15 text-ok' : 'bg-warn/15 text-warn'">{{ llm.api_key_set ? '已配置 Key' : '未配置 Key' }}</span>
      </div>
      <div class="grid gap-3 md:grid-cols-3">
        <div class="md:col-span-2"><label class="label">base_url</label><input v-model="llm.base_url" class="input mono" placeholder="https://your-gateway.com/v1" /></div>
        <div><label class="label">模型名</label><input v-model="llm.model" class="input mono" placeholder="your-model" /></div>
        <div><label class="label">api_key {{ llm.api_key_mask ? '(' + llm.api_key_mask + ')' : '' }}</label><input v-model="llm.api_key" type="password" class="input mono" placeholder="留空则保留原 Key" /></div>
        <div><label class="label">抽取用小模型（可选）</label><input v-model="llm.json_model" class="input mono" /></div>
        <div><label class="label">温度</label><input v-model.number="llm.temperature" step="0.05" type="number" class="input" /></div>
        <div><label class="label">最大输出 token</label><input v-model.number="llm.max_tokens" type="number" class="input" /></div>
        <div><label class="label">超时（秒）</label><input v-model.number="llm.timeout" type="number" class="input" /></div>
      </div>
      <div class="mt-3 flex items-center gap-2">
        <button class="btn-primary" @click="saveLlm">保存</button>
        <button class="btn-ghost" :disabled="testing" @click="testLlm">{{ testing ? '测试中…' : '测试连通' }}</button>
        <span v-if="testResult" class="text-xs" :class="testResult.ok ? 'text-ok' : 'text-danger'">
          {{ testResult.ok ? `连通正常（${testResult.elapsed_ms}ms）→ ${testResult.reply}` : testResult.error }}
        </span>
      </div>
    </div>

    <div class="card card-pad">
      <h3 class="mb-3 text-sm font-medium text-white">聊天策略</h3>
      <div class="grid gap-3 md:grid-cols-4">
        <div>
          <label class="label">语言模式</label>
          <select v-model="chat.lang_mode" class="input">
            <option value="follow">跟随对方</option>
            <option value="fixed">固定语言</option>
            <option value="persona">按人设</option>
            <option value="mix">混说保持主语言</option>
          </select>
        </div>
        <div>
          <label class="label">固定语言</label>
          <select v-model="chat.fixed_lang" class="input" :disabled="chat.lang_mode !== 'fixed'">
            <option v-for="l in LANGS" :key="l.v" :value="l.v">{{ l.label }}</option>
          </select>
        </div>
        <div><label class="label">本人手动回复后让路（分钟）</label><input v-model.number="chat.manual_yield_minutes" type="number" class="input" /></div>
        <div class="flex items-end">
          <label class="flex items-center gap-2 text-xs text-slate-300">
            <input v-model="chat.reply_in_offhours" type="checkbox" class="h-4 w-4 rounded border-line bg-ink-900" />
            非活跃时段也回复
          </label>
        </div>
      </div>
      <button class="btn-primary btn-sm mt-3" @click="saveChat">保存策略</button>
    </div>

    <div class="card card-pad">
      <h3 class="mb-3 text-sm font-medium text-white">控制 bot（BotFather 的 token）</h3>
      <div class="grid gap-3 md:grid-cols-3">
        <div class="md:col-span-2">
          <label class="label">token {{ bot.token_mask ? '(' + bot.token_mask + ')' : '' }}</label>
          <input v-model="bot.token" type="password" class="input mono" placeholder="留空则保留原 token" />
        </div>
        <div><label class="label">管理员 TG ID（逗号分隔）</label><input v-model="bot.admin_ids" class="input mono" /></div>
      </div>
      <p class="mt-2 text-[11px] text-slate-500">指令：/status /stop /resume /pause 编号 /skip @某人 /takeover @某人</p>
      <button class="btn-primary btn-sm mt-2" @click="saveBot">保存</button>
    </div>

    <div class="grid gap-4 md:grid-cols-2">
      <div class="card card-pad">
        <h3 class="mb-3 text-sm font-medium text-white">修改密码</h3>
        <div class="space-y-2">
          <div><label class="label">原密码</label><input v-model="pwd.old_password" type="password" class="input" /></div>
          <div><label class="label">新密码（≥10 位，三类字符）</label><input v-model="pwd.new_password" type="password" class="input" /></div>
          <button class="btn-primary btn-sm" @click="changePwd">更新密码</button>
        </div>
      </div>

      <div class="card card-pad">
        <h3 class="mb-3 text-sm font-medium text-white">两步验证 {{ auth.totpEnabled ? '（已开启）' : '' }}</h3>
        <template v-if="!auth.totpEnabled">
          <button class="btn-ghost btn-sm" @click="setup2fa">生成密钥</button>
          <div v-if="twofa.secret" class="mt-3 space-y-2">
            <div class="mono break-all rounded bg-ink-900 px-2 py-1.5 text-[11px] text-accent">{{ twofa.secret }}</div>
            <div class="text-[11px] text-slate-500">加到 Google Authenticator / 1Password，然后输入 6 位码</div>
            <input v-model="twofa.code" class="input mono" maxlength="6" placeholder="000000" />
            <button class="btn-primary btn-sm" @click="enable2fa">开启</button>
          </div>
        </template>
        <template v-else>
          <div class="space-y-2">
            <div><label class="label">输入密码关闭</label><input v-model="twofa.password" type="password" class="input" /></div>
            <button class="btn-danger btn-sm" @click="disable2fa">关闭两步验证</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
