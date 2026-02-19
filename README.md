# HashPass

<div align="center">

**内存硬度客户端谜题邀请码系统**

*公平 · 原子化 · 无数据库*

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## 什么是 HashPass？

HashPass 是一个**无数据库邀请码分发系统**，基于 Client Puzzles 架构和内存硬度工作量证明（Argon2d）。系统通过**内存原子锁**创建公平的竞争机制：

- 每轮谜题只有一个获胜者（原子化验证）
- 无 GPU/ASIC 挖矿（每次哈希需 64MB+ RAM）
- 无代理攻击（计算绑定到客户端 IP）
- 无多账户滥用（硬件指纹绑定）
- 无机器人（Cloudflare Turnstile 人机验证）
- 无数据库（纯内存状态）

**核心机制**：所有用户竞争解同一道谜题。第一个提交有效答案的用户获得邀请码，谜题立即重置——使所有其他用户的计算成果作废。

---

## 快速开始

### 环境要求

- Python 3.9+
- [uv](https://github.com/astral-sh/uv)（推荐）或 pip

### 安装

```bash
# 克隆仓库
git clone https://github.com/yourusername/hashpass.git
cd hashpass

# 安装依赖
uv pip install -e .

# 创建环境配置
cp .env.example .env
# 编辑 .env，至少设置 ADMIN_TOKEN

# 启动服务器（必须单进程）
python main.py
```

访问 **http://localhost:8000** 开始挖矿！

---

## 配置

### 环境变量

复制 `.env.example` 为 `.env` 并按需修改：

```bash
# 管理员 Token（必填）
ADMIN_TOKEN=your_secure_admin_token

# 服务器端口
PORT=8000

# Cloudflare Turnstile（开发模式）
TURNSTILE_TEST_MODE=true
TURNSTILE_SITE_KEY=1x00000000000000000000AA
TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA

# 难度设置
HASHPASS_DIFFICULTY=3
HASHPASS_MIN_DIFFICULTY=1
HASHPASS_MAX_DIFFICULTY=6
HASHPASS_TARGET_TIME=60      # 目标解题时间（秒）
HASHPASS_TARGET_TIMEOUT=300  # 超时时间（秒）

# Argon2 参数
HASHPASS_ARGON2_TIME_COST=3
HASHPASS_ARGON2_MEMORY_COST=65536  # KB（64MB）
HASHPASS_ARGON2_PARALLELISM=1
HASHPASS_WORKER_COUNT=4            # 前端并行 Worker 数量
```

详见 `.env.example` 中的完整注释说明。

### Turnstile 配置

**开发模式**（自动通过所有验证）：
```bash
TURNSTILE_TEST_MODE=true
TURNSTILE_SITE_KEY=1x00000000000000000000AA
TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA
```

**生产模式**：
1. 前往 [Cloudflare Turnstile 控制台](https://dash.cloudflare.com/?to=/:account/turnstile)
2. 创建新的站点 Widget
3. 复制 Site Key 和 Secret Key
4. 更新 `.env`：
   ```bash
   TURNSTILE_TEST_MODE=false
   TURNSTILE_SITE_KEY=你的真实_site_key
   TURNSTILE_SECRET_KEY=你的真实_secret_key
   ```

### Webhook 配置（可选）

用户获胜时，HashPass 可以通知你的外部服务：

**Payload 格式**：
```json
{
  "visitor_id": "设备指纹哈希",
  "invite_code": "HASHPASS-ABC123XYZ"
}
```

**配置示例**：
```bash
WEBHOOK_URL=https://your-domain.com/api/webhook
WEBHOOK_TOKEN=your_secret_bearer_token
```

携带 Bearer Token 时，请求头为：
```
Authorization: Bearer your_secret_bearer_token
```

**行为特征**：
- 异步发送（不阻塞主流程）
- 5 秒超时，失败自动重试（指数退避）
- 失败写入日志，不影响邀请码发放

---

## 工作原理

### 挖矿流程

```
用户打开页面
    │
    ▼
ThumbmarkJS 生成设备指纹
    │
    ▼
Cloudflare Turnstile 人机验证
    │
    ▼
WebSocket 连接 /api/ws?token=<turnstile_token>
    │
    ▼
服务器颁发 Session Token
    │
    ▼
POST /api/puzzle → 获取 seed、difficulty、Argon2 参数
    │
    ▼
获取 Cloudflare Trace 数据（IP 绑定）
    │
    ▼
启动 N 个 Web Worker 并行计算
    │
    ├── Worker 0: nonce = 0, 4, 8, ...
    ├── Worker 1: nonce = 1, 5, 9, ...
    ├── Worker 2: nonce = 2, 6, 10, ...
    └── Worker 3: nonce = 3, 7, 11, ...
         │
         ▼
    Argon2d(nonce, salt=seed+fingerprint+traceData)
    直到找到前 N 位为 0 的哈希
         │
         ▼
POST /api/verify → 提交解答
         │
    ┌────┴────┐
    │         │
  第一名    其他人
    │         │
    ▼         ▼
获得邀请码  409 Conflict
    │
    ▼
广播 PUZZLE_RESET 给所有矿工
```

### 服务端验证流程

```
接收 /api/verify 请求
    │
    ├─ 验证 Session Token（IP 绑定检查）
    ├─ 检查 IP 黑名单
    ├─ 验证 TraceData IP 与请求 IP 一致
    ├─ 快速检查 seed 是否已变（锁前）
    │
    ▼ 进入 asyncio.Lock 临界区
    │
    ├─ 二次检查 seed（DCL 模式）
    ├─ 计算解题耗时（仅含挖矿时间）
    ├─ ProcessPoolExecutor 验证 Argon2 哈希（非阻塞）
    ├─ 生成 HMAC 派生邀请码
    ├─ 发送异步 Webhook 通知
    ├─ 动态难度调整
    ├─ 重置谜题 + 广播 PUZZLE_RESET
    └─ 重启超时检查器
    │
    ▼ 退出临界区
    │
    └─ 异步写入 verify.json 日志
```

### 关键设计

**1. 原子锁**：`asyncio.Lock` 确保每轮谜题只有一个获胜者，防止竞态条件。

**2. 内存硬度算法**：每次哈希计算需要 64MB RAM（Argon2d），从根本上阻断 GPU 农场。

**3. IP 绑定**：计算盐值包含客户端 IP，在其他 IP 提交会验证失败，防止代理攻击。

**4. 硬件指纹**：ThumbmarkJS 通过 Canvas、WebGL、Audio 等采集设备特征，绑定解答到物理设备。

**5. 双层 Token 机制**：
- **Turnstile Token**（一次性）：首次建立 WebSocket 时验证
- **Session Token**（持久化）：服务器生成，绑定 IP，断开后保留 5 分钟支持重连

**6. 动态难度（比例步进算法）**：

基于 `log2(目标中点 / 实际耗时)` 计算调整步进：

| 解题耗时 | 偏离程度 | 调整幅度 |
|---------|---------|---------|
| 1 秒 | 极快（75 倍） | +4 bit |
| 5 秒 | 很快（15 倍） | +3 bit |
| 10 秒 | 较快（7.5 倍） | +2 bit |
| 25 秒 | 稍快（3 倍） | +1 bit |
| 目标窗口内 | 正常 | 不变 |
| 超时 | 超慢 | 至少 -2 bit |

每 +1 bit = 难度翻倍，每 -1 bit = 难度减半。步进限制在 [-4, +4] 范围。

**7. 进程池优化**：`ProcessPoolExecutor` 绕过 Python GIL，在独立进程中验证 Argon2，主事件循环保持响应。

**8. uvloop 加速（Linux/macOS）**：自动检测并启用，提升 WebSocket 广播 30-40% 性能，Windows 下降级为标准 asyncio。

### 难度参考

```
难度 1：约 2 次哈希      (~秒级)
难度 2：约 4 次哈希      (~秒级)
难度 3：约 8 次哈希      (~秒级)
难度 4：约 16 次哈希     (~数秒)
难度 8：约 256 次哈希    (~数十秒)
难度 12：约 4096 次哈希  (~数分钟)
难度 16：约 65536 次哈希 (~十余分钟)
```

（实际用时取决于硬件和 Argon2 参数）

---

## API 参考

### 公共 API

#### `POST /api/puzzle`

获取当前谜题参数。

**请求头**：`Authorization: Bearer <session_token>`

**请求体**：
```json
{
  "visitorId": "设备指纹"
}
```

**响应**：
```json
{
  "seed": "a1b2c3d4...",
  "difficulty": 4,
  "memory_cost": 65536,
  "time_cost": 3,
  "parallelism": 1,
  "worker_count": 4,
  "puzzle_start_time": 1234567890.0,
  "last_solve_time": 87.3,
  "average_solve_time": 95.2
}
```

---

#### `POST /api/verify`

提交谜题解答。

**请求头**：`Authorization: Bearer <session_token>`

**请求体**：
```json
{
  "visitorId": "设备指纹",
  "nonce": 42856,
  "submittedSeed": "a1b2c3d4...",
  "traceData": "ip=1.2.3.4\nts=...",
  "hash": "0000abcd..."
}
```

**成功（200）**：
```json
{
  "invite_code": "HASHPASS-XyZ123"
}
```

**错误**：
- `401 Unauthorized`：Session Token 无效或已过期
- `403 Forbidden`：IP 不匹配或被封禁
- `409 Conflict`：谜题已被他人解出（seed 已变）
- `400 Bad Request`：哈希验证失败

---

#### `WS /api/ws?token=<token>`

实时谜题重置通知和网络统计。

**客户端 → 服务器**：
```json
{"type": "ping"}
{"type": "mining_start"}
{"type": "mining_stop"}
{"type": "hashrate", "payload": {"rate": 123.45}}
```

**服务器 → 客户端**：
```json
// 首次连接：颁发 Session Token
{"type": "SESSION_TOKEN", "token": "..."}

// 心跳响应
{"type": "PONG", "online": 5}

// 谜题重置通知
{"type": "PUZZLE_RESET", "seed": "abc...", "difficulty": 4}

// 全网算力统计（每 5 秒广播）
{"type": "NETWORK_HASHRATE", "total_hashrate": 456.78, "active_miners": 3, "timestamp": 1234567890.0}
```

---

#### `GET /api/turnstile/config`

获取 Turnstile 公开配置。

**响应**：
```json
{
  "site_key": "1x00000000000000000000AA",
  "test_mode": true
}
```

---

#### `GET /api/health`

健康检查。

**响应**：
```json
{
  "status": "ok",
  "current_seed": "a1b2c3d4..."
}
```

---

#### `GET /api/dev/trace`

模拟 Cloudflare Trace（本地开发用）。

**响应**（纯文本）：
```
ip=127.0.0.1
ts=1736338496
visit_scheme=http
uag=Mozilla/5.0...
```

---

### 管理 API

所有管理端点需要请求头：`Authorization: Bearer <ADMIN_TOKEN>`

#### 状态查询

| 端点 | 描述 |
|------|------|
| `GET /api/admin/status` | 完整系统状态快照 |
| `GET /api/admin/miners` | 活跃矿工列表（含算力） |
| `GET /api/admin/sessions` | Session Token 列表 |
| `GET /api/admin/blacklist` | 封禁 IP 列表 |

#### 日志查询

| 端点 | 描述 |
|------|------|
| `GET /api/admin/logs` | 邀请码日志（分页、搜索、文件选择） |
| `GET /api/admin/logs/stats` | 邀请码日志聚合统计 |
| `GET /api/admin/applogs` | 应用日志（分页、搜索、级别过滤） |

#### 参数调整（调整后自动重置谜题）

| 端点 | 描述 |
|------|------|
| `POST /api/admin/difficulty` | 调整难度参数 |
| `POST /api/admin/target-time` | 调整目标时间窗口 |
| `POST /api/admin/argon2` | 调整 Argon2 参数 |
| `POST /api/admin/worker-count` | 设置前端 Worker 数量 |
| `POST /api/admin/max-nonce-speed` | 设置最大计算速度限制 |

#### 管理操作

| 端点 | 描述 |
|------|------|
| `POST /api/admin/reset-puzzle` | 强制重置谜题 |
| `POST /api/admin/kick-all` | 断开所有连接并撤销所有 Token |
| `POST /api/admin/kick` | 封禁 IP + 踢出 + 撤销 Token |
| `POST /api/admin/unban` | 从黑名单移除 IP |
| `POST /api/admin/clear-sessions` | 清空所有 Session Token |
| `POST /api/admin/regenerate-hmac` | 重新生成 HMAC 密钥 |

#### 管理 WebSocket

```
WS /api/admin/ws?token=<admin_token>
```

每 2 秒推送一次系统状态快照：
```json
{
  "type": "STATUS_UPDATE",
  "active_miners": 5,
  "online_connections": 8,
  "total_hashrate": 1234.56,
  "difficulty": 4,
  "mining_time": 87.3,
  "last_solve_time": 95.2,
  "banned_count": 2,
  "current_seed": "a1b2c3d4...",
  "hashrate_chart_history": [...],
  "solve_time_chart_history": [...]
}
```

---

## 架构

### 目录结构

```
hashpass/
├── main.py                        # FastAPI 应用入口、中间件、生命周期
├── pyproject.toml                 # 项目依赖配置
├── .env.example                   # 环境变量示例
│
├── src/
│   ├── api/
│   │   ├── routes.py              # 公共 API（puzzle、verify、ws 等）
│   │   └── admin.py               # 管理 API（status、miners、logs、操作等）
│   │
│   ├── core/
│   │   ├── state.py               # 全局 SystemState 单例（锁、种子、难度、会话）
│   │   ├── crypto.py              # Argon2d 验证 + HMAC 邀请码生成
│   │   ├── turnstile.py           # Cloudflare Turnstile Token 验证
│   │   ├── webhook.py             # 异步 Webhook 通知（重试+指数退避）
│   │   ├── executor.py            # ProcessPoolExecutor（绕过 GIL）
│   │   ├── event_loop.py          # uvloop 初始化（Linux/macOS）
│   │   ├── useragent.py           # User-Agent 验证（阻止机器人）
│   │   ├── admin_auth.py          # 管理员 Bearer Token 认证
│   │   └── log_config.py          # 日志配置（文件锁处理器）
│   │
│   └── models/
│       └── schemas.py             # Pydantic 数据模型
│
└── static/
    ├── index.html                 # 主挖矿界面
    ├── app.js                     # 前端入口（初始化、指纹、Turnstile）
    ├── worker.js                  # Web Worker（Argon2d 计算）
    ├── js/
    │   ├── state.js               # 全局前端状态
    │   ├── mining.js              # 挖矿编排（多 Worker 管理）
    │   ├── websocket.js           # WebSocket 客户端（重连、Session Token）
    │   ├── turnstile.js           # Turnstile 组件管理
    │   ├── hashrate.js            # 算力显示（本地 + 全网）
    │   ├── logger.js              # 日志面板（智能高亮）
    │   ├── theme.js               # 主题切换（Light/Dark/System）
    │   └── utils.js               # 格式化工具
    ├── css/
    │   └── custom.css             # 自定义 CSS 变量和样式
    ├── admin.html                 # 管理后台界面
    └── admin/
        ├── app.js                 # 管理后台入口（登录、Tab 切换）
        ├── css/admin.css          # 管理后台样式
        └── js/
            ├── state.js           # 管理后台状态
            ├── api.js             # 管理 API 客户端
            ├── websocket.js       # 管理 WebSocket（实时状态）
            ├── dashboard.js       # 仪表盘（指标卡片、Chart.js 趋势图）
            ├── params.js          # 参数调整面板
            ├── logs.js            # 邀请码日志（分页、搜索）
            ├── applogs.js         # 应用日志（分页、搜索、级别过滤）
            └── operations.js      # 管理操作（踢出、封禁、重置）
```

### 技术栈

**后端**：
- **FastAPI** — 异步 Web 框架
- **argon2-cffi** — 内存硬哈希
- **httpx** — 异步 HTTP 客户端（Turnstile + Webhook）
- **uvloop** — 高性能事件循环（Linux/macOS）
- **aiofiles** — 异步文件 I/O
- **ProcessPoolExecutor** — 并行 Argon2 验证（绕过 GIL）

**前端**：
- **Tailwind CSS** + **Pico.css** — 样式框架
- **hash-wasm**（WASM）— 浏览器端 Argon2 计算
- **ThumbmarkJS** — 设备指纹
- **Web Workers** — 非阻塞并行计算
- **Chart.js** — 管理后台趋势图
- **ES Modules + Import Maps** — 模块化依赖管理

### 全局状态（`SystemState`）

```python
class SystemState:
    # 谜题状态
    current_seed: str          # 当前谜题种子（32字节 hex）
    difficulty: int            # 当前难度（前导零位数）
    min_difficulty: int
    max_difficulty: int
    target_time: int           # 目标解题时间（秒）
    target_timeout: int        # 超时时间（秒）

    # 原子锁（核心）
    lock: asyncio.Lock

    # Argon2 配置
    argon2_time_cost: int
    argon2_memory_cost: int    # KB，默认 64MB
    argon2_parallelism: int
    worker_count: int          # 前端 Worker 数量
    max_nonce_speed: int       # 最大计算速度（0=禁用）

    # HMAC 密钥（256-bit，重启可持久化）
    hmac_secret: bytes

    # 挖矿追踪
    active_miners: set         # 正在挖矿的 WebSocket
    total_mining_time: float   # 累计挖矿时间
    is_mining_active: bool     # 是否有矿工在线

    # WebSocket 连接
    active_connections: set    # 所有活跃连接
    admin_connections: set     # 管理员连接

    # Session Token
    session_tokens: dict       # token → {websocket, ip, created_at, ...}

    # 算力统计
    client_hashrates: dict     # websocket → {rate, timestamp, ip}

    # IP 黑名单（持久化到 blacklist.json）
    banned_ips: set

    # 后台任务
    timeout_task: Task         # 超时检查
    aggregation_task: Task     # 算力聚合（5秒间隔）
    cleanup_task: Task         # Session 清理（60秒间隔）
```

---

## 管理后台

访问 `http://localhost:8000/admin` 进入管理后台。

### 功能模块

**仪表盘**：
- 10 个实时统计卡片（矿工数、算力、难度、解题时间等）
- Chart.js 趋势图（全网算力 + 解题时间历史）
- 活跃矿工列表（IP、算力、在线时长、封禁操作）
- IP 黑名单管理

**参数调整**：
- 难度参数（初始值、最小值、最大值）
- 目标时间窗口（目标时间、超时时间）
- Argon2 参数（时间成本、内存成本、并行度）
- 前端 Worker 数量（1-32）
- 计算速度限制（nonce/s，0 = 禁用）

**邀请码日志**：
- 分页查询 verify.json（每页 50 条）
- 全文搜索（IP、邀请码、访客 ID 等）
- 多文件切换（含轮转归档文件）
- 统计信息（总数、唯一访客、平均/中位数解题时间）

**应用日志**：
- 分页查询 log/hashpass.log（每页 100 行）
- 级别过滤（DEBUG / INFO / WARNING / ERROR / CRITICAL）
- 日志高亮（错误红色、警告黄色）

**管理操作**：
- 强制重置谜题
- 踢出所有矿工（断开连接 + 撤销 Token）
- 清除所有会话
- 封禁/解封 IP
- 重新生成 HMAC 密钥（使所有已签发邀请码失效）

### 安全机制

- **HMAC 常量时间比较**：防止时序攻击
- **防暴力破解**：10 次失败后锁定 IP 5 分钟
- **路径穿越防护**：日志文件白名单校验
- **XSS 防护**：所有动态内容使用 `textContent` 渲染

---

## 生产部署

### 关键约束：必须单进程

`asyncio.Lock` 和内存状态是进程本地的。多 Worker 部署会产生多个独立状态，破坏原子性保证。

**必须使用 `--workers 1`**：
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

### Systemd 服务

创建 `/etc/systemd/system/hashpass.service`：

```ini
[Unit]
Description=HashPass Invite Code System
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/hashpass
EnvironmentFile=/var/www/hashpass/.env
ExecStart=/usr/local/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable hashpass
sudo systemctl start hashpass
sudo systemctl status hashpass
```

### Nginx 反向代理

```nginx
upstream hashpass {
    server 127.0.0.1:8000;
}

server {
    listen 443 ssl;
    server_name hashpass.example.com;

    # WebSocket 端点（需要特殊配置）
    location /api/ws {
        proxy_pass http://hashpass;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # 管理 WebSocket
    location /api/admin/ws {
        proxy_pass http://hashpass;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
    }

    # 其他端点
    location / {
        proxy_pass http://hashpass;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Cloudflare 配置

1. **DNS**：添加 A 记录指向服务器
2. **代理**：启用 Cloudflare 代理（橙色云朵图标）
3. **SSL/TLS**：设置为 "Full" 或 "Full (strict)"
4. **WebSocket**：默认已启用，无需额外配置
5. **Turnstile**：在控制台创建 Widget 并配置域名

验证 Cloudflare Trace 是否正常：
```bash
curl https://your-domain.com/cdn-cgi/trace
```

### 内存需求估算

| 组件 | 内存占用 |
|------|---------|
| 基础进程 | ~50MB |
| 每个 ProcessPoolExecutor Worker | ~50-100MB |
| 每次 Argon2 验证（临时） | 64MB |
| 每个 WebSocket 连接 | ~1-2KB |

建议最低配置：**512MB RAM**（4 核 CPU，`argon2_memory_cost=65536`）。

---

## 安全机制

### 防御能力

| 攻击方式 | 防御机制 | 技术细节 |
|---------|---------|---------|
| 自动化机器人 | Cloudflare Turnstile | 人机挑战验证 |
| GPU 挖矿农场 | 内存硬哈希 | Argon2d 每次需 64MB RAM |
| 代理攻击 | IP 绑定 | TraceData IP 混入盐值，提交时验证 |
| 多账户滥用 | 硬件指纹 | ThumbmarkJS 设备签名 |
| 竞态条件 | 原子锁 | `asyncio.Lock` 串行化验证 |
| Token 重放 | Session 绑定 | Session Token 绑定 IP，带过期时间 |
| 脚本攻击 | UA 过滤 | 阻止 curl、wget、Python、Node 等 |
| 暴力破解管理后台 | 失败锁定 | 10 次失败锁定 IP 5 分钟 |

### 安全限制

以下场景**无法防御**（设计限制）：
- 与受害者 IP 相同范围的攻击者
- 浏览器引擎级别的指纹欺骗
- 高内存系统用户（Argon2 难度由设计决定）

---

## 审计日志

所有成功验证记录到 `verify.json`，自动轮转（超过 1000 条时归档）。

**日志格式**：
```json
{
  "timestamp": "2026-02-20T12:34:56.789Z",
  "invite_code": "HASHPASS-ABC123",
  "visitor_id": "设备指纹",
  "nonce": 42856,
  "hash": "0000abcd...",
  "seed": "a1b2c3d4...",
  "real_ip": "203.0.113.45",
  "trace_data": "ip=203.0.113.45\nts=...",
  "difficulty": 4,
  "solve_time": 87.3,
  "new_difficulty": 4,
  "adjustment_reason": "Solved in 87.3s (target: 30-120s), no change"
}
```

**轮转机制**：
- 主文件 `verify.json` 超过 1000 条自动归档
- 归档文件格式：`verify_YYYYMMDD_HHMMSS.json`
- 日志写入异步非阻塞，失败不影响邀请码发放

**文件锁**：
- Windows：`msvcrt.locking`（锁定首字节）
- Unix/Linux/macOS：`fcntl.flock`（独占锁）
- 应用日志使用 `LockedTimedRotatingFileHandler`

---

## 故障排查

### "Puzzle already solved" (409)

正常行为——有人抢先获胜，谜题已重置。等待或直接开始挖新谜题。

### "Identity mismatch" (403)

TraceData IP 与请求 IP 不匹配。
- **本地开发**：确保使用 `/api/dev/trace` 端点
- **生产环境**：检查 Cloudflare 代理配置，确认 `X-Real-IP` 正确传递

### "Invalid or expired session token" (401)

Session Token 过期或 IP 已变更。刷新页面重新获取。

### WebSocket 立即关闭（1008）

Token 无效或已过期。刷新页面重新通过 Turnstile 验证。

### 难度不自动调整

- 确认矿工通过 WebSocket 发送了 `mining_start`/`mining_stop` 消息
- 检查难度是否已达到 `min_difficulty` 或 `max_difficulty` 边界
- 只有有矿工挖矿时才计入解题时间

### 全网算力显示 0

- 确认前端通过 WebSocket 发送 `hashrate` 消息
- 算力数据 10 秒无更新后自动清零

### 内存占用过高

- 减小 `HASHPASS_ARGON2_MEMORY_COST`（会降低防 GPU 能力）
- 减少 `HASHPASS_WORKER_COUNT`

### 验证速度慢

- 检查日志确认 ProcessPoolExecutor 已初始化
- 降低 `HASHPASS_ARGON2_TIME_COST`（减少安全性）

---

## 常见问题

### 为什么必须单进程运行？

`asyncio.Lock` 是进程本地的。多进程 = 多个独立锁 = 破坏原子性。进程 A 中有人赢得了谜题，进程 B 对此毫不知情，仍会接受旧种子的答案，导致多人获得邀请码。

### 不使用 Cloudflare 可以吗？

可以，但失去 IP 绑定能力。系统会降级使用 `request.client.host`，该值可被伪造。生产环境**强烈建议**使用 Cloudflare。

### 服务器重启后会怎样？

谜题种子重置，所有进行中的挖矿作废。IP 黑名单持久化到 `blacklist.json` 会保留；HMAC 密钥若配置了 `HASHPASS_HMAC_SECRET` 也会保留，否则随机重新生成（导致所有已签发邀请码失效）。

### 邀请码会过期吗？

默认不过期。邀请码由 HMAC 签名生成，没有时间戳。若需要过期机制，在 `src/core/crypto.py` 中加入时间戳即可。

### WebSocket 断开后挖矿会停止吗？

不会。挖矿继续进行，WebSocket 仅提供实时通知（如"谜题已被他人解出"）。断开期间仍可提交答案，Session Token 保留 5 分钟。

---

## 贡献指南

欢迎提交 Pull Request！

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/amazing-feature`
3. 提交更改：`git commit -m 'Add amazing feature'`
4. 推送分支：`git push origin feature/amazing-feature`
5. 创建 Pull Request

**提交前注意**：
- 保持 `--workers 1` 单进程要求
- 在开发模式和生产模式下都测试 Turnstile
- 验证 WebSocket 功能正常
- 确认审计日志正确写入

---

## 鸣谢

- [FastAPI](https://fastapi.tiangolo.com/) — 现代异步 Python 框架
- [Argon2](https://github.com/P-H-C/phc-winner-argon2) — 密码哈希竞赛获奖算法
- [hash-wasm](https://github.com/Daninet/hash-wasm) — 高性能浏览器哈希库
- [ThumbmarkJS](https://github.com/thumbmarkjs/thumbmarkjs) — 浏览器设备指纹
- [Cloudflare](https://www.cloudflare.com/) — CDN 与 Turnstile 人机验证
- [uvloop](https://github.com/MagicStack/uvloop) — 超高速 asyncio 事件循环

---

## 许可证

MIT License — 详见 [LICENSE](LICENSE) 文件。

---

<div align="center">

**公平、原子化、无数据库的邀请码分发系统**

[提交 Bug](https://github.com/yourusername/hashpass/issues) · [功能请求](https://github.com/yourusername/hashpass/issues) · [技术文档](CLAUDE.md)

</div>
