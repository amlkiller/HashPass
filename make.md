# HashPass 项目制作步骤

> 基于 Atomic Hash-Lock Protocol 的邀请码分发系统完整制作指南

## 📋 目录

1. [环境准备](#1-环境准备)
2. [后端开发](#2-后端开发)
3. [前端开发](#3-前端开发)
4. [本地测试](#4-本地测试)
5. [部署上线](#5-部署上线)
6. [验证测试](#6-验证测试)

---

## 1. 环境准备

### 1.1 检查 Python 版本

```bash
python --version  # 需要 >= 3.9
```

### 1.2 初始化项目（已完成）

```bash
uv init
```

### 1.3 配置依赖

编辑 `pyproject.toml`，添加必要依赖：

```toml
[project]
name = "hashpass"
version = "0.1.0"
description = "Atomic Hash-Lock Protocol Invite System"
readme = "README.md"
requires-python = ">=3.9"
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "argon2-cffi>=23.1.0",
    "pydantic>=2.5.0",
    "python-multipart>=0.0.6",
]
```

### 1.4 安装依赖

```bash
uv pip install -e .
# 或者使用 uv sync（如果使用 uv 工作流）
```

---

## 2. 后端开发

### 2.1 创建目录结构

```bash
mkdir -p src/{api,core,models}
mkdir static
mkdir templates
```

最终目录结构：
```
Hashpass/
├── src/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py          # API 路由
│   ├── core/
│   │   ├── __init__.py
│   │   ├── state.py           # 全局状态管理
│   │   └── crypto.py          # Argon2 验证逻辑
│   └── models/
│       ├── __init__.py
│       └── schemas.py         # Pydantic 模型
├── static/                    # 前端静态文件
│   ├── index.html
│   ├── app.js
│   └── style.css
├── main.py                    # FastAPI 入口
└── pyproject.toml
```

### 2.2 实现全局状态管理

创建 `src/core/state.py`：

```python
import asyncio
import secrets
from argon2 import PasswordHasher, Type

class SystemState:
    """全局内存状态 - 维护原子锁和谜题"""
    def __init__(self):
        self.lock = asyncio.Lock()
        self.current_seed = secrets.token_hex(16)
        self.difficulty = 4  # 哈希前 N 位为 0

        # Argon2 配置: 64MB 内存, 3 轮迭代
        self.ph = PasswordHasher(
            time_cost=3,
            memory_cost=65536,  # 64MB
            parallelism=1,
            hash_len=32,
            type=Type.ID
        )

    def reset_puzzle(self):
        """重置谜题（获胜后调用）"""
        self.current_seed = secrets.token_hex(16)

# 全局单例
state = SystemState()
```

### 2.3 实现数据模型

创建 `src/models/schemas.py`：

```python
from pydantic import BaseModel

class PuzzleResponse(BaseModel):
    seed: str
    difficulty: int
    memory_cost: int

class Submission(BaseModel):
    visitorId: str      # ThumbmarkJS 指纹
    nonce: int          # 挖矿 nonce
    submittedSeed: str  # 提交时的 seed
    traceData: str      # Cloudflare trace 数据
    hash: str           # 计算出的哈希值

class VerifyResponse(BaseModel):
    invite_code: str
```

### 2.4 实现验证逻辑

创建 `src/core/crypto.py`：

```python
import argon2.low_level as alg
from fastapi import HTTPException

def verify_argon2_solution(
    nonce: int,
    seed: str,
    visitor_id: str,
    trace_data: str,
    submitted_hash: str,
    difficulty: int
) -> bool:
    """验证 Argon2 哈希解"""

    # 重建 Salt（必须与前端一致）
    salt_raw = (seed + visitor_id + trace_data).encode('utf-8')

    # 重新计算哈希
    try:
        raw_hash = alg.hash_secret_raw(
            secret=str(nonce).encode('utf-8'),
            salt=salt_raw,
            time_cost=3,
            memory_cost=65536,
            parallelism=1,
            hash_len=32,
            type=alg.Type.ID
        )
        hash_hex = raw_hash.hex()

        # 验证客户端提交的哈希是否正确
        if hash_hex != submitted_hash:
            return False

        # 验证难度（前 N 位为 0）
        if not hash_hex.startswith("0" * difficulty):
            return False

        return True

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hash verification failed: {str(e)}")
```

### 2.5 实现 API 路由

创建 `src/api/routes.py`：

```python
import secrets
from fastapi import APIRouter, Request, HTTPException
from src.core.state import state
from src.core.crypto import verify_argon2_solution
from src.models.schemas import PuzzleResponse, Submission, VerifyResponse

router = APIRouter(prefix="/api")

@router.get("/puzzle", response_model=PuzzleResponse)
async def get_puzzle():
    """获取当前谜题"""
    return PuzzleResponse(
        seed=state.current_seed,
        difficulty=state.difficulty,
        memory_cost=65536
    )

@router.post("/verify", response_model=VerifyResponse)
async def verify_solution(sub: Submission, request: Request):
    """验证哈希解并分发邀请码"""

    # 1. 获取真实 IP（Cloudflare Header）
    real_ip = request.headers.get("cf-connecting-ip")
    if not real_ip:
        # 本地开发回退
        real_ip = request.client.host

    # 2. 反作弊：验证 TraceData 中的 IP 是否匹配
    if f"ip={real_ip}" not in sub.traceData:
        raise HTTPException(
            status_code=403,
            detail="Identity mismatch: TraceData IP doesn't match request IP"
        )

    # 3. 进入原子锁临界区
    async with state.lock:
        # 3.1 检查 Seed 是否过期
        if state.current_seed != sub.submittedSeed:
            raise HTTPException(
                status_code=409,
                detail="Puzzle already solved by someone else"
            )

        # 3.2 验证哈希解
        is_valid = verify_argon2_solution(
            nonce=sub.nonce,
            seed=sub.submittedSeed,
            visitor_id=sub.visitorId,
            trace_data=sub.traceData,
            submitted_hash=sub.hash,
            difficulty=state.difficulty
        )

        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail="Invalid hash solution"
            )

        # 4. 获胜处理：生成邀请码并重置谜题
        invite_code = f"HASHPASS-{secrets.token_urlsafe(16)}"
        state.reset_puzzle()

        return VerifyResponse(invite_code=invite_code)

@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "current_seed": state.current_seed[:8] + "..."}
```

### 2.6 修改主入口文件

编辑 `main.py`：

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.api.routes import router

app = FastAPI(
    title="HashPass",
    description="Atomic Hash-Lock Protocol Invite System",
    version="1.0.0"
)

# 挂载 API 路由
app.include_router(router)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    """返回前端页面"""
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    # ⚠️ 必须单进程模式（workers=1）
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)
```

### 2.7 创建 `__init__.py` 文件

```bash
touch src/__init__.py
touch src/api/__init__.py
touch src/core/__init__.py
touch src/models/__init__.py
```

---

## 3. 前端开发

### 3.1 创建 HTML 页面

创建 `static/index.html`：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HashPass - Atomic Hash-Lock Protocol</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@1/css/pico.min.css">
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <main class="container">
        <article>
            <header>
                <h1>🔐 HashPass</h1>
                <p>Ephemeral Puzzles. Memory-Hard Proofs.</p>
            </header>

            <section id="status">
                <p><strong>状态:</strong> <span id="statusText">准备中...</span></p>
                <p><strong>设备指纹:</strong> <code id="fingerprint">计算中...</code></p>
                <p><strong>当前难度:</strong> <span id="difficulty">-</span></p>
                <progress id="progress" style="display:none;"></progress>
            </section>

            <section id="controls">
                <button id="startBtn" onclick="startMining()">开始挖矿</button>
                <button id="stopBtn" onclick="stopMining()" disabled>停止</button>
            </section>

            <section id="result" style="display:none;">
                <h3>恭喜获胜! 🎉</h3>
                <p><strong>邀请码:</strong></p>
                <input type="text" id="inviteCode" readonly>
                <button onclick="copyCode()">复制</button>
            </section>

            <section id="logs">
                <h4>日志</h4>
                <div id="logBox" style="height:200px; overflow-y:auto; background:#f0f0f0; padding:10px; font-family:monospace; font-size:12px;"></div>
            </section>
        </article>
    </main>

    <script type="module" src="/static/app.js"></script>
</body>
</html>
```

### 3.2 创建 CSS 样式

创建 `static/style.css`：

```css
body {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    min-height: 100vh;
}

article {
    margin-top: 2rem;
    box-shadow: 0 10px 40px rgba(0,0,0,0.3);
}

#logBox {
    white-space: pre-wrap;
    word-wrap: break-word;
}

#result input {
    font-weight: bold;
    color: #667eea;
}

button {
    margin: 0.5rem;
}

code {
    background: #e0e0e0;
    padding: 2px 6px;
    border-radius: 3px;
}
```

### 3.3 创建 JavaScript 挖矿逻辑

创建 `static/app.js`：

```javascript
import { getFingerprint } from 'https://esm.sh/@thumbmarkjs/thumbmarkjs@0.14.9';
import { argon2id } from 'https://esm.sh/hash-wasm@4.11.0';

let mining = false;
let visitorId = '';

// 初始化
(async function init() {
    log('正在获取设备指纹...');
    const fp = await getFingerprint();
    visitorId = fp.hash;
    document.getElementById('fingerprint').textContent = visitorId;
    log(`设备指纹: ${visitorId}`);

    // 获取当前难度
    const puzzle = await fetch('/api/puzzle').then(r => r.json());
    document.getElementById('difficulty').textContent = puzzle.difficulty;
    document.getElementById('statusText').textContent = '就绪';
})();

async function startMining() {
    if (mining) return;
    mining = true;

    document.getElementById('startBtn').disabled = true;
    document.getElementById('stopBtn').disabled = false;
    document.getElementById('progress').style.display = 'block';
    document.getElementById('statusText').textContent = '挖矿中...';

    try {
        // 1. 获取网络特征（关键步骤）
        log('正在获取 Cloudflare Trace...');
        const traceData = await fetch('/cdn-cgi/trace').then(r => r.text());
        log(`Trace 数据: ${traceData.split('\n')[0]}`);

        // 2. 获取当前谜题
        const puzzle = await fetch('/api/puzzle').then(r => r.json());
        log(`谜题 Seed: ${puzzle.seed}`);
        log(`难度: ${puzzle.difficulty} (前${puzzle.difficulty}位为0)`);
        log(`内存需求: ${puzzle.memory_cost / 1024}MB`);

        // 3. 开始挖矿
        const result = await mineArgon2(puzzle.seed, traceData, puzzle.difficulty);

        // 4. 提交结果
        if (result) {
            await submitSolution(result, puzzle.seed, traceData);
        }

    } catch (error) {
        log(`错误: ${error.message}`, 'error');
    } finally {
        stopMining();
    }
}

async function mineArgon2(seed, traceData, difficulty) {
    let nonce = 0;
    const saltString = seed + visitorId + traceData;
    const salt = new TextEncoder().encode(saltString);

    log(`开始计算 Argon2id (内存硬依赖)...`);
    const startTime = Date.now();

    while (mining) {
        nonce++;

        const hash = await argon2id({
            password: nonce.toString(),
            salt: salt,
            memoryCost: 65536, // 64MB
            timeCost: 3,
            parallelism: 1,
            hashLength: 32,
            outputType: 'hex'
        });

        if (nonce % 10 === 0) {
            const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
            log(`尝试 #${nonce}, 哈希: ${hash.substring(0, 16)}... (${elapsed}s)`);
        }

        if (hash.startsWith('0'.repeat(difficulty))) {
            const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
            log(`✅ 找到解! Nonce: ${nonce}, Hash: ${hash}`, 'success');
            log(`总耗时: ${elapsed}秒`);
            return { nonce, hash };
        }
    }

    return null;
}

async function submitSolution(result, submittedSeed, traceData) {
    log('正在提交解...');

    const response = await fetch('/api/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            visitorId: visitorId,
            nonce: result.nonce,
            submittedSeed: submittedSeed,
            traceData: traceData,
            hash: result.hash
        })
    });

    if (response.ok) {
        const data = await response.json();
        log(`🎉 获胜! 邀请码: ${data.invite_code}`, 'success');
        document.getElementById('result').style.display = 'block';
        document.getElementById('inviteCode').value = data.invite_code;
    } else {
        const error = await response.json();
        log(`提交失败: ${error.detail}`, 'error');
    }
}

function stopMining() {
    mining = false;
    document.getElementById('startBtn').disabled = false;
    document.getElementById('stopBtn').disabled = true;
    document.getElementById('progress').style.display = 'none';
    document.getElementById('statusText').textContent = '已停止';
}

function copyCode() {
    const input = document.getElementById('inviteCode');
    input.select();
    document.execCommand('copy');
    log('邀请码已复制到剪贴板');
}

function log(message, type = 'info') {
    const logBox = document.getElementById('logBox');
    const time = new Date().toLocaleTimeString();
    const color = type === 'error' ? 'red' : type === 'success' ? 'green' : 'black';
    logBox.innerHTML += `<span style="color:${color}">[${time}] ${message}</span>\n`;
    logBox.scrollTop = logBox.scrollHeight;
}

// 导出全局函数
window.startMining = startMining;
window.stopMining = stopMining;
window.copyCode = copyCode;
```

---

## 4. 本地测试

### 4.1 启动开发服务器

```bash
# 方式1: 直接运行
python main.py

# 方式2: 使用 uvicorn
uvicorn main:app --reload --workers 1
```

### 4.2 访问测试

打开浏览器访问：`http://localhost:8000`

### 4.3 测试检查清单

- [ ] 页面正常加载，显示设备指纹
- [ ] 点击"开始挖矿"按钮，日志显示 Trace 数据
- [ ] 挖矿过程中日志持续更新
- [ ] 找到解后自动提交
- [ ] 成功获取邀请码
- [ ] 第二个用户同时挖矿时，先完成者获胜，后完成者收到 409 错误

### 4.4 模拟并发测试

在两个浏览器标签页中同时点击"开始挖矿"，验证原子锁机制。

---

## 5. 部署上线

### 5.1 部署到 Cloudflare Workers（推荐前端）

前端可以部署到 Cloudflare Pages 或静态托管服务。

### 5.2 部署后端到 VPS

#### 准备生产环境

1. 安装依赖：
```bash
uv pip install -e .
```

2. 配置 systemd 服务（确保单进程）：

创建 `/etc/systemd/system/hashpass.service`：

```ini
[Unit]
Description=HashPass Atomic Hash-Lock Service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/hashpass
Environment="PATH=/usr/local/bin"
ExecStart=/usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always

[Install]
WantedBy=multi-user.target
```

3. 启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable hashpass
sudo systemctl start hashpass
```

#### 配置 Nginx 反向代理

创建 `/etc/nginx/sites-available/hashpass`：

```nginx
server {
    listen 80;
    server_name hashpass.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

#### 配置 Cloudflare

1. 在 Cloudflare DNS 中添加 A 记录指向服务器 IP
2. 开启 Cloudflare Proxy（橙色云朵）
3. 确保 SSL/TLS 模式为 "Full" 或 "Flexible"

### 5.3 环境变量配置（可选）

如果需要配置密钥，创建 `.env` 文件：

```bash
DIFFICULTY=4
MEMORY_COST=65536
SECRET_KEY=your-secret-key-here
```

修改 `src/core/state.py` 加载环境变量：

```python
import os
from dotenv import load_dotenv

load_dotenv()

class SystemState:
    def __init__(self):
        self.difficulty = int(os.getenv('DIFFICULTY', 4))
        # ...
```

---

## 6. 验证测试

### 6.1 生产环境测试

访问 `https://hashpass.yourdomain.com` 并测试：

- [ ] HTTPS 正常工作
- [ ] Cloudflare Trace 数据正确
- [ ] 挖矿功能正常
- [ ] 邀请码分发正常

### 6.2 反作弊测试

尝试以下攻击场景，验证防御机制：

1. **代理攻击**：使用 VPN 计算后切换 IP 提交 → 应返回 403
2. **重放攻击**：获胜后再次提交相同解 → 应返回 409
3. **并发攻击**：多个客户端同时提交 → 仅第一个成功

### 6.3 监控与日志

使用以下命令监控服务：

```bash
# 查看服务状态
sudo systemctl status hashpass

# 查看日志
sudo journalctl -u hashpass -f

# 监控内存使用
htop
```

---

## 🎯 完成检查清单

- [ ] 后端 API 正常运行
- [ ] 前端页面可访问
- [ ] 设备指纹获取成功
- [ ] Argon2 挖矿逻辑正确
- [ ] 原子锁机制有效
- [ ] 反作弊验证通过
- [ ] Cloudflare 集成正常
- [ ] 生产环境部署成功
- [ ] 邀请码分发正常

---

## 📚 参考资料

- FastAPI 文档: https://fastapi.tiangolo.com/
- Argon2 规范: https://github.com/P-H-C/phc-winner-argon2
- ThumbmarkJS: https://github.com/thumbmarkjs/thumbmarkjs
- Cloudflare Trace: https://cloudflare.com/cdn-cgi/trace

---

## ⚠️ 重要提醒

1. **单进程部署**：生产环境必须使用 `--workers 1`
2. **Cloudflare 依赖**：必须通过 Cloudflare 代理以获取正确的 Trace 数据
3. **内存配置**：确保服务器至少有 512MB 可用内存
4. **HTTPS**：生产环境必须使用 HTTPS，否则浏览器 API 可能受限

---

**项目完成！祝你部署顺利！** 🚀
