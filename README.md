# HashPass

<div align="center">

**🔐 Memory-Hard Client Puzzle System**

*Fair. Atomic. Database-Free.*

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## What is HashPass?

HashPass is a **zero-database invite code distribution system** powered by Client Puzzles and memory-hard proof-of-work. It uses an **in-memory atomic lock** to create a fair, race-based competition where:

- ✅ Only one winner per puzzle (atomic verification)
- ✅ No GPU/ASIC farming (64MB+ RAM per hash)
- ✅ No proxy attacks (IP-bound computations)
- ✅ No multi-accounting (hardware fingerprinting)
- ✅ No bots (Cloudflare Turnstile protection)
- ✅ No database (pure in-memory state)

**Core Mechanism**: All users race to solve the same puzzle. The first to submit a valid solution wins the invite code and the puzzle immediately resets - invalidating everyone else's work.

---

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/hashpass.git
cd hashpass

# Install dependencies
uv pip install -e .

# Create environment configuration
cp .env.example .env

# Start the server (MUST be single-worker)
python main.py
```

Visit **http://localhost:8000** and start mining!

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file with the following configuration:

```bash
# ========================================
# Server Configuration
# ========================================
PORT=8000  # Server port (default: 8000)

# ========================================
# Cloudflare Turnstile (Bot Protection)
# ========================================
# Get keys: https://dash.cloudflare.com/turnstile
TURNSTILE_SITE_KEY=1x00000000000000000000AA
TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA

# Development mode (auto-pass all challenges)
TURNSTILE_TEST_MODE=true

# ========================================
# Puzzle Difficulty Settings
# ========================================
# Initial difficulty level (1-6)
HASHPASS_DIFFICULTY=3

# Dynamic difficulty range
HASHPASS_MIN_DIFFICULTY=1
HASHPASS_MAX_DIFFICULTY=6

# Target solve time window (seconds)
HASHPASS_TARGET_TIME_MIN=30
HASHPASS_TARGET_TIME_MAX=120

# ========================================
# Argon2 Parameters (Advanced)
# ========================================
HASHPASS_ARGON2_TIME_COST=3         # Iteration count
HASHPASS_ARGON2_MEMORY_COST=65536   # Memory in KB (64MB)
HASHPASS_ARGON2_PARALLELISM=1       # Thread count (keep at 1)

# ========================================
# Webhook Integration (Optional)
# ========================================
# External service to notify on wins
WEBHOOK_URL=https://your-domain.com/api/webhook

# Optional Bearer Token for webhook authentication
WEBHOOK_TOKEN=your_secret_token_here

# Leave empty to disable webhooks
# WEBHOOK_URL=

# ========================================
# Performance Optimization
# ========================================
# Disable uvloop (Linux/macOS only)
# HASHPASS_DISABLE_UVLOOP=false
```

⚠️ **Important**: Changes to Argon2 parameters (`HASHPASS_ARGON2_*`) must be synchronized with client-side code (`static/app.js`). Mismatched parameters will cause all verifications to fail.

### Turnstile Setup

**Development Mode** (No real verification):
```bash
TURNSTILE_TEST_MODE=true
TURNSTILE_SITE_KEY=1x00000000000000000000AA
TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA
```

**Production Mode**:
1. Sign up at https://dash.cloudflare.com/turnstile
2. Create a new site widget
3. Copy your Site Key and Secret Key
4. Update `.env`:
   ```bash
   TURNSTILE_TEST_MODE=false
   TURNSTILE_SITE_KEY=your_actual_site_key
   TURNSTILE_SECRET_KEY=your_actual_secret_key
   ```

### Webhook Setup (Optional)

When a user wins, HashPass can notify your external service:

**Payload Format**:
```json
{
  "visitor_id": "device-fingerprint-hash",
  "invite_code": "HASHPASS-ABC123XYZ"
}
```

**Bearer Token Authentication**:

For secure webhook endpoints, configure a Bearer Token in your `.env`:

```bash
WEBHOOK_TOKEN=your_secret_token_here
```

When `WEBHOOK_TOKEN` is set, HashPass includes it in the request header:
```
Authorization: Bearer your_secret_token_here
```

**Example Webhook Receiver** (Python/FastAPI):
```python
from fastapi import Header, HTTPException

@app.post("/api/webhook")
async def receive_webhook(
    payload: dict,
    authorization: str = Header(None)
):
    # Validate Bearer Token
    expected_token = os.getenv("WEBHOOK_TOKEN")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = authorization.replace("Bearer ", "")
    if token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid token")

    # Process webhook
    visitor_id = payload["visitor_id"]
    invite_code = payload["invite_code"]
    # ... your logic here
```

**Behavior**:
- Sent asynchronously (non-blocking)
- 5-second timeout
- Failures are logged but don't affect invite code delivery
- Uses HTTPS in production for secure transmission

---

## 🎯 How It Works

### Mining Flow

```mermaid
sequenceDiagram
    participant Client
    participant Turnstile
    participant Server
    participant Worker

    Client->>Turnstile: Pass challenge
    Turnstile-->>Client: Token
    Client->>Server: GET /api/puzzle (with token)
    Server-->>Client: Seed + Difficulty

    Client->>Worker: Start mining
    loop Find valid hash
        Worker->>Worker: Argon2id(nonce, salt)
        Note over Worker: Salt = Seed + DeviceID + IP
    end

    Worker-->>Client: Found: nonce + hash
    Client->>Server: POST /api/verify

    alt First to arrive
        Server-->>Client: Invite Code ✓
        Server->>Server: Reset puzzle seed
        Server-->>All: Broadcast PUZZLE_RESET
    else Too slow
        Server-->>Client: 409 Conflict
    end
```

### Key Concepts

**1. Atomic Lock**: Python's `asyncio.Lock` ensures only one winner per puzzle round.

**2. Memory-Hard Algorithm**: Each hash computation requires 64MB RAM (Argon2id), preventing GPU farms.

**3. IP Binding**: Computation includes client IP in the salt. Solving on Server A and submitting from Client B fails verification.

**4. Hardware Fingerprinting**: ThumbmarkJS ties solutions to physical devices (Canvas/Audio/WebGL fingerprints).

**5. Dynamic Difficulty (Proportional Step)**: System automatically adjusts difficulty using a log2-proportional algorithm:
- Adjustment step = `floor(log2(deviation_ratio))`, clamped to 1~4 bits
- The further solve time deviates from the target midpoint, the larger the step
- Only counts time when miners are actively mining
- Timeout auto-resets puzzle with aggressive step (minimum -2 bits)

| Solve Time | Deviation | Step |
|------------|-----------|------|
| 1s | 75x fast | +4 bits |
| 5s | 15x fast | +3 bits |
| 10s | 7.5x fast | +2 bits |
| 25s | 3x fast | +1 bit |
| 30-120s | In range | 0 (no change) |
| 300s | 4x slow | -2 bits |
| 1000s | 13x slow | -3 bits |

**6. Network Hashrate Monitoring**: Real-time global mining statistics:
- Clients report hashrate via WebSocket
- Server aggregates and broadcasts total network hashrate
- Provides visibility into mining competition
- Stale data (>10s) automatically pruned

**7. Process Pool Optimization**: CPU-intensive Argon2 verification runs in parallel:
- ProcessPoolExecutor bypasses Python GIL
- Main event loop remains responsive during verification
- Worker count: CPU cores - 1 (reserves one for main process)

**8. Event Loop Optimization (uvloop)**: Automatic performance enhancement on Linux/macOS:
- **WebSocket Broadcasting**: 30-40% faster message delivery to concurrent miners
- **Atomic Lock Operations**: 5-10% reduced lock contention overhead
- **Connection Handling**: 2x more concurrent connections supported
- **Platform Support**:
  - ✅ **Linux** (production recommended): uvloop active
  - ✅ **macOS**: uvloop active
  - ⚠️ **Windows**: Standard asyncio (uvloop not supported, use WSL2 for production)
- **No configuration needed** - automatically detected and installed
- **Disable if needed**: Set `HASHPASS_DISABLE_UVLOOP=true` in environment

**Difficulty Scaling**:
```
Level 1:  ~16 attempts       (~1 second)
Level 2:  ~256 attempts      (~15 seconds)
Level 3:  ~4096 attempts     (~1 minute)
Level 4:  ~65536 attempts    (~15 minutes)
Level 5:  ~1M attempts       (~4 hours)
Level 6:  ~16M attempts      (~64 hours)
```

---

## 📡 API Reference

### GET `/api/puzzle`
Fetch current puzzle parameters.

**Headers**: `Authorization: Bearer <turnstile_token>`

**Response**:
```json
{
  "seed": "a1b2c3d4...",
  "difficulty": 4,
  "memory_cost": 65536,
  "time_cost": 3,
  "parallelism": 1
}
```

---

### POST `/api/verify`
Submit puzzle solution.

**Headers**: `Authorization: Bearer <turnstile_token>`

**Request**:
```json
{
  "visitorId": "device-fingerprint",
  "nonce": 42856,
  "submittedSeed": "a1b2c3d4...",
  "traceData": "ip=1.2.3.4\nts=...",
  "hash": "0000abcd..."
}
```

**Success Response (200)**:
```json
{
  "invite_code": "HASHPASS-XyZ123"
}
```

**Error Responses**:
- `403 Forbidden`: IP mismatch or invalid Turnstile token
- `409 Conflict`: Puzzle already solved (seed changed)
- `400 Bad Request`: Invalid hash (wrong difficulty)

---

### WebSocket `/api/ws?token=<token>`
Real-time puzzle reset notifications and network statistics.

**Client → Server**:
```json
{"type": "ping"}                                   // Heartbeat
{"type": "mining_start"}                           // Notify mining started
{"type": "mining_stop"}                            // Notify mining stopped
{"type": "hashrate", "payload": {"rate": 123.45}}  // Report hashrate (H/s)
```

**Server → Client**:
```json
// Heartbeat response
{"type": "PONG", "online": 5}

// Puzzle reset notification
{"type": "PUZZLE_RESET", "seed": "abc...", "difficulty": 4}

// Network hashrate statistics (broadcast every 2s)
{"type": "NETWORK_HASHRATE", "total_hashrate": 456.78, "active_miners": 3, "timestamp": 1234567890.0}
```

---

### GET `/api/turnstile/config`
Get Turnstile public configuration.

**Response**:
```json
{
  "site_key": "1x00000000000000000000AA",
  "test_mode": true
}
```

---

### GET `/api/health`
Health check endpoint.

**Response**:
```json
{
  "status": "ok",
  "current_seed": "a1b2c3d4..."
}
```

---

### GET `/api/dev/trace` (Development Only)
Mock Cloudflare Trace endpoint for local testing.

**Response**:
```
ip=127.0.0.1
ts=1736338496
visit_scheme=http
uag=Mozilla/5.0...
```

---

## 🏗️ Architecture

### Backend Stack

```
src/
├── api/
│   └── routes.py          # FastAPI endpoints + WebSocket
├── core/
│   ├── state.py           # Global SystemState (asyncio.Lock)
│   ├── crypto.py          # Argon2 verification + HMAC codes
│   ├── turnstile.py       # Cloudflare token verification
│   ├── webhook.py         # Async webhook notifications
│   ├── executor.py        # ProcessPoolExecutor (CPU-intensive tasks)
│   └── event_loop.py      # uvloop initialization
└── models/
    └── schemas.py         # Pydantic request/response models
```

**Technologies**:
- **FastAPI** - Async web framework
- **argon2-cffi** - Memory-hard hashing
- **httpx** - Async HTTP client (Turnstile + Webhooks)
- **uvloop** - High-performance event loop (Linux/macOS)
- **ProcessPoolExecutor** - Parallel Argon2 verification (bypasses GIL)

### Frontend Stack

```
static/
├── index.html            # UI (Preact + Pico.css)
├── app.js                # Mining logic + ThumbmarkJS
├── worker.js             # Web Worker (non-blocking Argon2)
└── style.css             # Dark/light theme styles
```

**Technologies**:
- **Preact** - Lightweight React alternative
- **hash-wasm** - Browser-side Argon2 (WASM)
- **ThumbmarkJS** - Hardware fingerprinting
- **Web Workers** - Non-blocking computation

---

## 🌐 Production Deployment

### Critical Requirement: Single Worker Mode

⚠️ **MUST run with `--workers 1`**

Multi-worker deployments break the atomic lock because each process has independent memory. This allows multiple winners per puzzle round.

### Systemd Service

Create `/etc/systemd/system/hashpass.service`:

```ini
[Unit]
Description=HashPass Service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/hashpass
Environment="PATH=/usr/local/bin:/usr/bin"
ExecStart=/usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Start service**:
```bash
sudo systemctl daemon-reload
sudo systemctl enable hashpass
sudo systemctl start hashpass
sudo systemctl status hashpass
```

---

### Nginx Reverse Proxy

```nginx
upstream hashpass {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name hashpass.example.com;

    # Static files
    location /static {
        alias /var/www/hashpass/static;
        expires 30d;
    }

    # WebSocket endpoint
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

    # API endpoints
    location / {
        proxy_pass http://hashpass;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

### Cloudflare Configuration

1. **DNS**: Add A record pointing to your server
2. **Proxy**: Enable Cloudflare proxy (orange cloud)
3. **SSL/TLS**: Set to "Full" or "Full (strict)"
4. **WebSockets**: Enabled by default (no config needed)
5. **Turnstile**: Configure widget on dashboard

**Verify Cloudflare Trace works**:
```bash
curl https://your-domain.com/cdn-cgi/trace
```

---

## 🔒 Security Mechanisms

### What HashPass Prevents

| Attack Vector | Defense Mechanism | Technical Detail |
|---------------|-------------------|------------------|
| **Bots** | Cloudflare Turnstile | Challenge-response verification on all endpoints |
| **GPU Farms** | Memory-hard algorithm | 64MB RAM per hash (Argon2id) |
| **Proxy Attacks** | IP binding | TraceData mixed into salt, verified on submit |
| **Multi-accounting** | Hardware fingerprinting | ThumbmarkJS device signature |
| **Race conditions** | Atomic lock | `asyncio.Lock` serializes verification |
| **Script automation** | Turnstile + Fingerprint | Combined bot detection + device binding |

### What HashPass Does NOT Prevent

- Determined attackers with matching IP addresses
- Browser engine-level fingerprint spoofing
- Users with high-memory systems having advantages (by design)

---

## 📊 Audit Logs

The system logs all successful verifications with **automatic log rotation**:

**Main Log File**: `verify.json` (always contains the latest records)

**Archived Files**: `verify_YYYYMMDD_HHMMSS.json` (created when main file reaches 1000 records)

**Log Entry Format**:
```json
{
  "timestamp": "2026-01-08T12:34:56.789Z",
  "invite_code": "HASHPASS-ABC123",
  "visitor_id": "device-fingerprint",
  "nonce": 42856,
  "hash": "0000abcd...",
  "seed": "a1b2c3d4...",
  "real_ip": "203.0.113.45",
  "trace_data": "ip=203.0.113.45\nts=...",
  "difficulty": 4,
  "solve_time": 87.3,
  "new_difficulty": 4,
  "adjustment_reason": "Perfect timing (87.3s within 30-120s)"
}
```

**Log Rotation Mechanism**:
- Automatically triggers when `verify.json` reaches 1000 records
- Moves old records to timestamped archive file
- Resets main file to empty array
- Prevents unbounded file growth
- Archive files preserved for historical analysis

**Use Cases**:
- Security audits (detect suspicious patterns)
- Performance analysis (solve time distributions)
- Anti-cheat (identify multi-account behavior)
- System optimization (tune difficulty parameters)
- Compliance tracking (record all invite code distributions)

**Note**: Logging is asynchronous and does NOT affect system operation. Failed writes are logged but don't prevent invite code distribution.

---

## ❓ FAQ

### Why single-worker only?

Python's `asyncio.Lock` is process-local. Multiple workers = multiple independent locks = broken atomicity. User A solves Worker 1's puzzle, but Worker 2 still accepts solutions for the old seed.

### Can I run without Cloudflare?

Yes, but you lose IP binding. The system falls back to `request.client.host` which can be spoofed. Production deployments **strongly recommended** to use Cloudflare.

### How does dynamic difficulty work?

The system uses a **proportional step algorithm** based on `log2` deviation from the target midpoint (75s by default):

- Solved much faster than target → large increase (up to +4 bits per round)
- Solved slightly faster → small increase (+1 bit)
- Solved within target window (30-120s) → no change
- Solved slightly slower → small decrease (-1 bit)
- Timeout (no solution after 120s) → aggressive decrease (at least -2 bits) + reset puzzle

This allows rapid convergence: e.g., from difficulty 4 to 24 in just 5 rounds (vs. 20 rounds with fixed +1 step).

Configure thresholds in `.env`:
```bash
HASHPASS_TARGET_TIME_MIN=30
HASHPASS_TARGET_TIME_MAX=120
```

### What happens if the server restarts?

The puzzle seed resets, invalidating all in-progress work. This is by design (ephemeral state). If persistence is needed, you can store the seed in Redis or a file, but this compromises the "zero-database" architecture.

### Do invite codes expire?

Not by default. The current implementation uses HMAC signatures without timestamps. To add expiration, modify `src/core/crypto.py` to include JWT-style expiry claims.

### What if WebSocket disconnects?

Mining continues normally. WebSocket only provides real-time notifications (e.g., "someone else won, stop wasting CPU"). You can still submit solutions without an active WebSocket connection.

### How does Turnstile token refresh work?

Tokens expire after 5 minutes. The widget automatically resets and requests a new challenge. The UI disables mining during refresh and re-enables once a new token is obtained.

---

## 🛠️ Troubleshooting

### "Puzzle already solved" errors
Normal behavior - someone else won first. The puzzle seed has reset. Start mining the new puzzle.

### "Identity mismatch" errors
Client's TraceData IP doesn't match server-detected IP.
- **Local dev**: Use `/api/dev/trace` endpoint
- **Production**: Verify Cloudflare configuration is correct
- Check that `X-Real-IP` header is being forwarded properly

### "Missing Turnstile token" errors
- Ensure `.env` file exists with `TURNSTILE_TEST_MODE=true` for development
- Check browser console for Turnstile Widget errors
- Verify Turnstile script loaded (check Network tab)
- Try refreshing the page to reinitialize Widget

### Turnstile Widget not rendering
- Check browser console for JavaScript errors
- Verify `https://challenges.cloudflare.com/turnstile/v0/api.js` is accessible
- Ensure no ad blockers are interfering
- Check `/api/turnstile/config` returns valid Site Key

### "403 Forbidden" on API requests
- **Frontend**: Check that `turnstileToken` is set before making requests
- **Backend**: Verify `TURNSTILE_TEST_MODE=true` in development
- **Production**: Confirm real Turnstile keys are set in environment

### WebSocket closes immediately (1008 code)
- Token missing or invalid in WebSocket URL
- Refresh page to get new Turnstile token
- Check server logs for validation errors

### Multiple workers warning
If deploying with process managers (systemd, supervisor), ensure `--workers 1` is set. Multiple workers break the atomic lock mechanism.

### WebSocket not connecting
- Check CORS settings
- Ensure WebSocket endpoint is accessible
- For production, use `wss://` (secure WebSocket)
- Verify firewall allows WebSocket connections

### Difficulty not adjusting
- Check that miners are sending `mining_start`/`mining_stop` messages
- Verify mining time is being tracked (check server logs)
- Ensure `HASHPASS_MIN_DIFFICULTY` and `HASHPASS_MAX_DIFFICULTY` are set correctly
- Difficulty only adjusts after a puzzle is solved or times out

### Network hashrate shows 0
- Ensure frontend is sending `hashrate` messages via WebSocket
- Check that WebSocket connection is established before mining starts
- Verify server is receiving and aggregating hashrate data
- Hashrate data becomes stale after 10 seconds of no updates

### High memory usage
- ProcessPoolExecutor creates worker processes (each uses ~50-100MB base memory)
- Each Argon2 verification uses 64MB temporarily
- Consider reducing `HASHPASS_ARGON2_MEMORY_COST` for low-memory systems (reduces anti-farming protection)
- Default worker count: CPU cores - 1 (can be reduced in `src/core/executor.py`)

### Slow verification times
- Check ProcessPoolExecutor is initialized (`[Executor] Process pool initialized` in logs)
- Verify system has enough CPU cores for worker processes
- High concurrent verification load may cause queuing
- Consider tuning `HASHPASS_ARGON2_TIME_COST` (lower = faster, but weaker anti-bot protection)

### Webhook not receiving requests
- Verify `WEBHOOK_URL` is set correctly in `.env`
- Check webhook endpoint is accessible (use `curl` to test)
- Review server logs for webhook errors
- Ensure webhook endpoint accepts POST requests
- Verify Bearer Token authentication if `WEBHOOK_TOKEN` is set

---

## 🧪 Testing

### Local Development

```bash
# Start server
python main.py

# Test API endpoints
curl http://localhost:8000/api/health
curl http://localhost:8000/api/puzzle
curl http://localhost:8000/api/dev/trace
```

### Concurrent Mining Test

1. Open two browser tabs at `http://localhost:8000`
2. Click "Start Mining" in both tabs simultaneously
3. First tab to find solution → receives invite code
4. Second tab → receives 409 Conflict error
5. Both tabs → receive WebSocket `PUZZLE_RESET` notification

### WebSocket Test

```javascript
// Browser console
const ws = new WebSocket('ws://localhost:8000/api/ws?token=test_token');
ws.onmessage = (e) => console.log('Received:', JSON.parse(e.data));
ws.onopen = () => ws.send(JSON.stringify({type: 'ping'}));
```

### Dynamic Difficulty Test

1. Set low initial difficulty: `HASHPASS_DIFFICULTY=1`
2. Mine puzzle quickly (should solve in <10 seconds)
3. Check logs: difficulty should auto-increase
4. Wait 120+ seconds without submitting → difficulty decreases

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

**Before submitting**:
- Ensure `--workers 1` requirement is preserved
- Test with Turnstile in both test and production modes
- Verify WebSocket functionality
- Check audit logs are correctly written

---

## 📝 Technical Documentation

For detailed technical documentation, see [CLAUDE.md](CLAUDE.md):
- Argon2 parameter tuning
- Cloudflare Trace integration details
- Memory requirements and scaling
- Security considerations
- Troubleshooting guide

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [FastAPI](https://fastapi.tiangolo.com/) - Modern async Python framework
- [Argon2](https://github.com/P-H-C/phc-winner-argon2) - Password Hashing Competition winner
- [hash-wasm](https://github.com/Daninet/hash-wasm) - High-performance browser hashing
- [ThumbmarkJS](https://github.com/thumbmarkjs/thumbmarkjs) - Browser fingerprinting
- [Cloudflare](https://www.cloudflare.com/) - CDN and Turnstile bot protection
- [uvloop](https://github.com/MagicStack/uvloop) - Ultra-fast asyncio event loop

---

<div align="center">

**Made with ❤️ for fair, atomic, database-free invite systems**

⭐ Star this repo if you find it useful!

[Report Bug](https://github.com/yourusername/hashpass/issues) · [Request Feature](https://github.com/yourusername/hashpass/issues) · [Documentation](CLAUDE.md)

</div>
