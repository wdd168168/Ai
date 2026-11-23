# AI 托管聊天机器人系统

接管 Telegram 个人账号，以账号本人的身份用 AI 自动对话：多语言、人设切换、风格模仿、
兴趣画像、语音条、主动发起会话、随时人工接管。

- 后端：Python 3.11 + FastAPI + Telethon（MTProto 用户客户端，非 Bot API）
- 数据：PostgreSQL 16；缓存/队列：Redis 7 + RQ
- 前端：Vue 3 + Vite + Tailwind（桌面 / 手机浏览器自适应）
- 语音：多 TTS provider 按语种路由，统一转 ogg/opus 单声道 48kHz 语音条
- ASR：faster-whisper（可切 OpenAI 兼容接口）
- 部署：Docker Compose 一键起，Nginx 反代，HTTPS 可接证书

---

## 一、5 分钟跑起来

```bash
# 1. 进入项目目录
cd ai-operator

# 2. 生成配置
cp .env.example .env
#    必改：SECRET_KEY / ADMIN_PASSWORD / POSTGRES_PASSWORD
#    加密会话的密钥（不填则从 SECRET_KEY 派生，建议单独生成）：
python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
#    模型：LLM_BASE_URL / LLM_API_KEY / LLM_MODEL（任何 OpenAI 兼容端点都行）
#    Telegram 应用：TG_API_ID / TG_API_HASH（去 my.telegram.org 申请，个人账号登录必需）

# 3. 启动（首次会拉镜像 + 装依赖，约 3-6 分钟）
docker compose up -d --build

# 4. 看日志确认起来了
docker compose logs -f backend
#    出现「已写入 12 个人设模板」「服务已启动」即可

# 5. 打开后台
#    http://你的服务器IP/            （或绑好域名后的 https://your.domain）
#    账号：.env 里的 ADMIN_USERNAME / ADMIN_PASSWORD
```

进去第一件事：**改密码 + 开两步验证**（系统设置页）。

### 配 HTTPS（推荐）

```bash
# 用 certbot 签发（把域名解析到这台机器）
sudo apt install certbot
sudo certbot certonly --standalone -d your.domain.com
# 把证书拷到项目里
mkdir -p nginx/certs && sudo cp /etc/letsencrypt/live/your.domain.com/{fullchain,privkey}.pem nginx/certs/
# 打开 docker-compose.yml 里 443 端口的注释、打开 nginx/default.conf 末尾 HTTPS 段的注释（改域名）
docker compose up -d
```

### 不带 Docker 的单机模式

适合先试功能（SQLite + 进程内队列，不需要 Postgres/Redis）：

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd frontend && npm install && npm run build && cp -r dist ../backend/static && cd ..
cd backend
cat > .env <<'EOF'
SECRET_KEY=换成随机串
ADMIN_PASSWORD=换成强密码
DATABASE_URL=sqlite+aiosqlite:///./app.db
QUEUE_BACKEND=inline
MEDIA_DIR=./media
EOF
python3 ../run.py     # 监听 8800（PORT 环境变量可改；没有执行权限就这样跑）
```

单机模式撑不起多账号长期跑，正式用请用 compose。

---

## 二、使用手册

### 1. 绑定账号（F1）

1. 系统设置 → 填 `TG_API_ID` / `TG_API_HASH`（或在账号里单独填）。
2. 账户管理 → 添加账号：备注名、手机号（带国家码，如 `+85512345678`）、设备型号、代理（可选）。
3. 点「登录」→ 系统向该号发验证码 → 输入验证码；开了两步验证的再输密码。
4. 登录成功后会话加密存库，**重启免登录**；点「启动」让它在后台常驻。

- 一号一会话、一出口：代理在账号里单独配（SOCKS5 / HTTP / MTProxy）。
- 设备指纹（型号、系统版本、客户端版本）在账号里固定，重登不变。
- 一个号出问题不影响别的号（每个号独立任务、独立重连）。

### 2. 配人设（F2）

人设管理：12 个内置模板可直接「复制」改，或新建。

可调字段：姓名、性别、年龄、职业、城市、时区、性格关键词、语气浓度 1-5、口头禅、
emoji 习惯、句长偏好、分段习惯、禁忌话题、默认亲密度、默认语言、音色 ID、语音比例、
语速、音调、活跃时段、背景设定。

- 「绑账号」把当前人设绑到账号；也可以建**自动切换规则**（按联系人或时段）。
- 「导出」得到 JSON，换机器「导入」即可带走。

### 3. 上下文与记忆（F3）

每个联系人独立记忆，绝不串台：

- 短期：最近 20 条完整对话随每轮一起喂给模型。
- 长期：每轮结束后自动抽取结构化事实（身份/工作/家人/喜好/约定/待办），下一轮按相关性检索注入。
- 会话详情页右侧能看到抽取到的事实、兴趣画像、未完成话题、情绪基线，可手动清空。

例：对方说「下周三去曼谷出差」→ 抽成 appointment 事实 → 隔两天再聊，模型会主动接上「曼谷那边怎么样」。

### 4. 风格学习（F4）

风格档案页：

- 「从账号拉取历史消息」直接读本人最近 300 条发言（最省事）。
- 或者「导入历史消息」：一行一条，粘贴你自己以前发过的话。
- 自动生成：平均句长、分段比例、emoji 率、口头禅、标点习惯、称呼习惯、活跃时段。
- 右边「手动修正」优先级最高，改完立刻生效。
- 每轮生成时按当前话题检索 6-10 条你的原话作为 few-shot 范例。

### 5. 兴趣画像（F5）

自动维护到每个联系人上：兴趣 TOP5（带判断依据）、回避话题、情绪基线、亲密度、未完成话题、关键事实。

- 每轮对话后异步更新，不阻塞回复。
- 老联系人可点「重建画像」，按历史记录批量冷启动（Redis 模式下走后台队列）。

### 6. 多语言（F6）

系统设置 → 聊天策略 → 语言模式：

| 模式 | 行为 |
|---|---|
| 跟随对方 | 检测对方消息语种，用同语种回 |
| 固定语言 | 永远用指定语言 |
| 按人设 | 用人设的默认语言 |
| 混说保持主语言 | 检测不到就回落到人设语言 |

支持：简体中文 / 台湾繁体国语 / 台语（闽南语） / 英语 / 越南语 / 高棉语。

⚠️ **台湾繁体国语（zh-TW）和台语（nan-TW）是两个独立选项**：前者是繁体字 + 台湾用词
（軟體/資訊/影片/預設/資料庫），后者是闽南语口语（阮/恁/毋/佮/咧）。输出的台湾文案会做
用词本地化 + 简繁一致性校验，混用会被检出。

### 7. 语音（F7）

语音管理页：

- 选语言 + 性别，试听该语种所有可用音色；调语速、音调。
- 人设里设语音比例（0-100），到比例就发语音条；`晚安/安慰/暧昧` 场景会加权。
- 收到对方语音条会自动转文字（Whisper），再进上下文。
- 少样本克隆：上传 30 秒 - 3 分钟样本 → 得到 voice_id → 填进人设的「音色 ID」。

底层按语种路由：中文/英语/越南语/高棉语都有可用音色；主通道失败会自动切备用朗读通道，
再不行才退回文字（不会让消息丢）。

> 高棉语、越南语的**原生音色数量受服务商限制**（各 1-2 个），要更多音色就配 Azure 或克隆。

### 8. 主动会话（F8）

主动任务页：

1. 新建任务：选账号、目标（开场白方向）、人设、发送时段、每天人数、发送间隔。
2. 「预览候选」按标签 / 最近互动天数筛人 → 「入队」写进队列。
3. 「启动」后调度器每分钟检查，在时段内按额度发；两人之间的间隔随机 3-10 分钟（可调）。
4. 批次内开场白**强制互不相同**（把已用过的作为负例喂给模型）。
5. 对方回复后自动转成正常对话继续跟进。
6. 「试一条」立刻发一条验证效果，不用等。

### 9. 接管与急停（F9）

- 顶栏「全部停发」：所有账号立即停；「恢复」一键恢复。
- 账号行：AI 开关、自动回复开关、启动/停止。
- 会话详情页：「一键停」只停这一个联系人；「恢复接管」放开。
- 联系人页：暂停 / 静默 2 小时 / 拉黑。
- 你在手机上手动回一句 → 系统检测到（非 AI 发出的消息）→ 这个联系人 **AI 让路 20 分钟**（可配）。
- 控制 bot：在系统设置填 BotFather 的 token 和管理员 TG ID，之后用 `/stop`、`/resume`、
  `/pause 3`、`/skip @someone`、`/takeover @someone`、`/status` 远程控制。
- 高危操作（全停、删除账号、清空记忆、退出）都要二次确认，且写审计日志。

### 10. 日志与用量（F10）

- 操作审计：谁、何时、做了什么、对哪个对象、IP。
- 模型用量：每次调用的 tokens、耗时、成功/失败与错误。
- 控制指令：控制 bot 收到的每条指令及处理结果。
- 每条 AI 消息都记了「用了哪个人设、参考了哪几条记忆、几秒打字」，在会话详情里能展开。

### 11. 稳定性与安全（F11）

- 断线自动重连（指数退避，最长 5 分钟一次），单账号崩溃不影响其它账号。
- FloodWait 精确等待：拿到多少秒就等多少秒，冷却期内不再发。
- 三级限速：分钟 / 小时 / 天，按账号可覆盖，主动发起比被动回复更保守。
- 新号预热：前 36 小时只被动回复；之后每周放量（8 → 16 → 32 … 到账号日上限）。
- 会话文件 Fernet 加密存储；后台强密码 + 两步验证；敏感操作全审计。
- 所有密钥、模型、端口走环境变量，代码里不写死任何 key。

---

## 三、常见问题

**发不出消息 / 账号一直离线**
看账户管理里那行的 `last_error`。最常见：api_id/api_hash 不对、代理不通、会话失效（点「重新登录」）。

**模型报错**
系统设置 → 模型配置 → 点「测试连通」。返回 4xx 多半是 key 或 model 名不对；超时看 base_url 是否可达。

**语音没声音**
语音管理页点「试听这条」。中文/英语走免费通道；高棉/越南语若主通道没返回音频会自动切备用。
克隆音色需要额外配 `TTS_CLONE_BASE_URL` / `TTS_CLONE_API_KEY`。

**会被封号吗**
任何自动化都有风险。系统内置的预热期、三级限速、随机间隔、作息模拟就是为了把风险压低，
但**不要拿来群发广告**，那必然封。新号先只做被动回复，稳定几天再少量主动。

**数据在哪**
`docker compose` 的 `appdata`/`pgdata` 卷里。媒体文件在 `/data/media`。
备份：`docker compose exec db pg_dump -U op operator > backup.sql`。

---

## 四、目录结构

```
ai-operator/
├── docker-compose.yml       # db + redis + backend + worker + web
├── .env.example             # 所有配置项（含注释）
├── run.py                   # 单进程启动入口
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py          # 入口 / 生命周期 / 静态托管
│   │   ├── config.py        # 全部配置（env）
│   │   ├── models.py        # 数据模型
│   │   ├── api/             # auth/accounts/personas/contacts/chats/proactive/style_voice/system
│   │   ├── core/            # llm/lang/typing/persona/memory/style/profile/tts/asr/ratelimit
│   │   ├── tg/              # manager（客户端池）/login/handlers（对话编排）/controlbot
│   │   ├── workers/         # jobs/scheduler/queue/tasks（RQ）
│   │   └── seed.py          # 12 个人设模板
│   └── tests/
│       ├── mock_llm.py      # 本地 mock 模型端点
│       └── selftest_core.py # 38 项核心逻辑自测
├── frontend/                # Vue3 + Vite + Tailwind，12 个页面
├── nginx/default.conf
└── docs/验收对照表.md
```

自测：

```bash
cd backend
python tests/selftest_core.py     # 38 项：语言/拟人化/风格/记忆/画像/生成链路
```

## 多厂商模型轮换（v2）

`LLM_PROVIDERS` 支持配置一条轮换链，按顺序尝试，前一家额度用完 / 限流 / 模型下线会自动换下一家，
不会因为某一家挂掉就哑巴。每项格式：

```json
[
  {"name":"groq-120b","base_url":"https://api.groq.com/openai/v1","api_key":"gsk_xxx",
   "models":["openai/gpt-oss-120b"],"json_models":["openai/gpt-oss-120b"],
   "extra":{"reasoning_effort":"low"}},
  {"name":"groq-qwen","base_url":"https://api.groq.com/openai/v1","api_key":"gsk_xxx",
   "models":["qwen/qwen3.8-27b"]}
]
```

- `extra` 会原样并入请求体（例如 `reasoning_effort: low`，避免思考过程吃掉额度导致空回复）
- `json_models` 用于记忆抽取、画像这类结构化任务，可单独指定
- 语音转写同样有降级链：Groq Whisper → Gemini 多模态 → OpenAI Whisper

