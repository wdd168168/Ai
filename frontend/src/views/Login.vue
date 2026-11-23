<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { authApi } from '../lib/api'
import { auth, ui } from '../lib/store'

const router = useRouter()
const username = ref('')
const password = ref('')
const totp = ref('')
const needTotp = ref(false)
const loading = ref(false)

async function submit() {
  if (!username.value || !password.value) return
  loading.value = true
  try {
    const data = await authApi.login(username.value.trim(), password.value, totp.value.trim())
    auth.setLogin(data)
    ui.ok('登录成功')
    router.push('/overview')
  } catch (e) {
    if (e.message.includes('两步验证')) needTotp.value = true
    ui.err(e.message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="relative grid min-h-screen place-items-center overflow-hidden px-4">
    <div class="pointer-events-none absolute inset-0 opacity-40"
         style="background:radial-gradient(600px 400px at 50% 0%, rgba(79,209,197,.16), transparent 60%)"></div>
    <div class="relative w-full max-w-sm">
      <div class="mb-8 text-center">
        <div class="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl bg-accent text-xl font-bold text-ink-950">A</div>
        <h1 class="text-xl font-semibold text-white">AI 托管控制台</h1>
        <p class="mt-1 text-xs text-slate-500">账号 · 人设 · 上下文 · 语音 · 接管</p>
      </div>

      <form class="card card-pad space-y-4" @submit.prevent="submit">
        <div>
          <label class="label">用户名</label>
          <input v-model="username" class="input" autocomplete="username" placeholder="admin" />
        </div>
        <div>
          <label class="label">密码</label>
          <input v-model="password" type="password" class="input" autocomplete="current-password" placeholder="••••••••" />
        </div>
        <div v-if="needTotp">
          <label class="label">两步验证码</label>
          <input v-model="totp" class="input mono" inputmode="numeric" maxlength="6" placeholder="000000" />
        </div>
        <button class="btn-primary w-full" :disabled="loading">{{ loading ? '验证中…' : '登 录' }}</button>
        <p class="text-center text-[11px] text-slate-600">首次部署后请立刻修改默认密码并开启两步验证</p>
      </form>
    </div>
  </div>
</template>
