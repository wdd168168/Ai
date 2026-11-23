import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './style.css'
import { auth } from './lib/store'

const routes = [
  { path: '/login', component: () => import('./views/Login.vue'), meta: { public: true } },
  { path: '/', redirect: '/overview' },
  { path: '/overview', component: () => import('./views/Overview.vue'), meta: { title: '总览' } },
  { path: '/accounts', component: () => import('./views/Accounts.vue'), meta: { title: '账户管理' } },
  { path: '/personas', component: () => import('./views/Personas.vue'), meta: { title: '人设管理' } },
  { path: '/chats', component: () => import('./views/Chats.vue'), meta: { title: '会话列表' } },
  { path: '/chats/:id', component: () => import('./views/ChatDetail.vue'), meta: { title: '会话详情' } },
  { path: '/contacts', component: () => import('./views/Contacts.vue'), meta: { title: '联系人' } },
  { path: '/proactive', component: () => import('./views/Proactive.vue'), meta: { title: '主动任务' } },
  { path: '/style', component: () => import('./views/Style.vue'), meta: { title: '风格档案' } },
  { path: '/voice', component: () => import('./views/Voice.vue'), meta: { title: '语音管理' } },
  { path: '/logs', component: () => import('./views/Logs.vue'), meta: { title: '日志与用量' } },
  { path: '/settings', component: () => import('./views/Settings.vue'), meta: { title: '系统设置' } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  if (!to.meta.public && !auth.token) return { path: '/login' }
  if (to.path === '/login' && auth.token) return { path: '/overview' }
  return true
})

createApp(App).use(router).mount('#app')
