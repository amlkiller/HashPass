# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**HashPass** is an innovative invite code distribution system based on Client Puzzles architecture. It uses **Argon2id memory-hard proof-of-work** with an **in-memory atomic lock** to create a fair, race-based invite code system that:

- Requires no database (pure in-memory state)
- Uses asyncio.Lock for atomic puzzle seed management
- Prevents GPU/ASIC farming via memory-hard hashing (64MB+ per computation)
- Binds computations to IP addresses via Cloudflare Trace data
- Uses hardware fingerprinting (ThumbmarkJS) to prevent multi-account abuse

### Core Concept

The system maintains a single global puzzle seed in memory. When a user solves the puzzle (finds a hash with N leading zeros), they win the invite code and the seed immediately resets - invalidating all other users' work in progress.

## Commands

### Development

```bash
# Install dependencies
uv pip install -e .

# Start development server (single worker - CRITICAL)
python main.py

# Or with uvicorn
uvicorn main:app --reload --workers 1
```

### Production Deployment

**⚠️ CRITICAL**: Must run with `--workers 1` (single process mode)

Multi-worker deployments will break the atomic lock mechanism since each process has its own memory space.

```bash
# Production deployment
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

### Event Loop Optimization (uvloop)

**Automatic Performance Enhancement**

On Linux/macOS systems, HashPass automatically uses **uvloop** to replace the default asyncio event loop, providing significant performance improvements:

- **WebSocket Broadcasting**: 30-40% faster message delivery to concurrent miners
- **Atomic Lock Operations**: 5-10% reduced lock contention overhead
- **Connection Handling**: 2x more concurrent connections supported

**Platform Support**:
- ✅ **Linux** (production recommended): uvloop active
- ✅ **macOS**: uvloop active
- ⚠️ **Windows**: Standard asyncio (uvloop not supported)
  - Recommended for Windows users: Use WSL2 for production-like performance

**Configuration**:
No configuration needed - uvloop is automatically detected and installed if available (included in `uvicorn[standard]` dependency).

**Verification**:
Check startup logs for event loop confirmation:
```
[Event Loop] ✓ uvloop installed successfully on linux
[HashPass] Event loop: Loop
```

**Technical Details**:
- uvloop is installed at application startup (main.py:1-2)
- Installation happens BEFORE asyncio.Lock creation (state.py:16)
- Single-worker architecture remains unchanged
- All asyncio primitives (Lock, WebSocket, create_task) work identically

**Rollback**: If needed, disable via environment variable:
```bash
export HASHPASS_DISABLE_UVLOOP=true
python main.py
```

## Architecture

### Backend Structure

```
src/
├── api/
│   └── routes.py          # API endpoints (/puzzle, /verify, /ws, /turnstile/config)
├── core/
│   ├── state.py           # Global SystemState singleton with asyncio.Lock
│   ├── crypto.py          # Argon2 verification & HMAC invite code generation
│   ├── turnstile.py       # Cloudflare Turnstile token verification
│   ├── webhook.py         # Webhook notification system (async POST on win)
│   ├── executor.py        # ProcessPoolExecutor for CPU-intensive Argon2 verification
│   └── event_loop.py      # uvloop initialization and event loop management
└── models/
    └── schemas.py         # Pydantic models (PuzzleResponse, Submission, etc.)
```

### Key Components

#### 1. Global State Management (`src/core/state.py`)

The `SystemState` class maintains:
- `asyncio.Lock`: Ensures atomic verification (one winner only)
- `current_seed`: The active puzzle seed (resets on each win)
- `difficulty`: Number of leading zeros required in hash (dynamically adjusted)
- `min_difficulty` / `max_difficulty`: Difficulty adjustment bounds
- `target_time_min` / `target_time_max`: Target solve time range for difficulty adjustment
- `hmac_secret`: Server-side secret for generating invite codes (regenerates on restart)
- `active_connections`: Set of WebSocket connections for real-time notifications
- `active_miners`: Set of miners currently mining (for accurate time tracking)
- `client_hashrates`: Dict tracking each client's hashrate for network statistics
- `puzzle_start_time`: Timestamp when current puzzle started
- `total_mining_time`: Cumulative mining time (only counts when miners are active)
- `timeout_task`: Background task for puzzle timeout checking
- `aggregation_task`: Background task for network hashrate aggregation

**Critical Design**: This is a singleton (`state = SystemState()`). All API requests interact with the same instance.

**Dynamic Difficulty System**:
- Automatically adjusts difficulty based on solve times
- Only counts time when miners are actively mining (pauses when all miners disconnect)
- Timeout checker runs in background, auto-decreasing difficulty if puzzle unsolved after target_time_max

#### 2. Proof-of-Work System

**Client-side (static/app.js)**:
1. Get device fingerprint via ThumbmarkJS
2. Fetch Cloudflare Trace data (IP binding)
3. Get puzzle seed from `/api/puzzle`
4. Compute: `Hash = Argon2id(nonce, salt=seed+fingerprint+traceData)`
5. Find nonce where hash starts with N zeros
6. Submit to `/api/verify`

**Server-side (src/api/routes.py)**:
1. Verify IP matches TraceData (anti-proxy attack)
2. Enter atomic lock critical section
3. Check seed hasn't changed (first-come-first-served)
4. Use ProcessPoolExecutor to verify hash (non-blocking, CPU-intensive)
5. Generate HMAC-derived invite code
6. Adjust difficulty dynamically based on solve time
7. Send async Webhook notification (non-blocking)
8. Reset puzzle seed
9. Broadcast reset via WebSocket
10. Restart timeout checker task

#### 3. Process Pool Executor (`src/core/executor.py`)

**Purpose**: Prevents Argon2 verification from blocking the asyncio event loop.

**How it works**:
- ProcessPoolExecutor spawns worker processes (bypasses Python GIL)
- CPU-intensive hash verification runs in separate process
- Main event loop remains responsive during verification
- Initialized at application startup, shutdown at exit

**Configuration**:
```python
# Default: CPU cores - 1 (reserves one core for main process)
max_workers = max(1, os.cpu_count() - 1)
```

**Integration**:
```python
# routes.py:146-159
executor = get_process_pool()
is_valid, error_message = await loop.run_in_executor(
    executor,
    verify_argon2_solution,  # CPU-intensive function
    sub.nonce, sub.submittedSeed, sub.visitorId, sub.traceData, sub.hash, state.difficulty
)
```

#### 4. Security Mechanisms

**IP Binding** (`routes.py:121-125`):
- Salt includes Cloudflare Trace data with user's IP
- Server validates submitted TraceData matches request IP
- Prevents "compute on powerful server, submit from user's IP" attacks

**Atomic Lock** (`routes.py:135-215`):
- `async with state.lock` ensures serial verification
- First valid solution wins, others get 409 Conflict
- Seed resets immediately after validation

**HMAC Invite Codes** (`crypto.py:51-85`):
- Codes derived from `HMAC-SHA256(secret, fingerprint:nonce:seed)`
- No database needed - code validity can be verified by recomputing HMAC
- Secret regenerates on server restart (invalidates old codes)

#### 5. Real-time Communication & Network Statistics

**WebSocket Protocol** (`routes.py:247-331`):

**Connection**: Clients connect to `/ws?token=<turnstile_token>` endpoint

**Client → Server Messages**:
```json
{"type": "ping"}                              // Heartbeat (get online count)
{"type": "mining_start"}                      // Notify server mining started
{"type": "mining_stop"}                       // Notify server mining stopped
{"type": "hashrate", "payload": {"rate": 123.45}}  // Report client hashrate (H/s)
```

**Server → Client Messages**:
```json
{"type": "PONG", "online": 5}                 // Heartbeat response
{"type": "PUZZLE_RESET", "seed": "abc...", "difficulty": 4}  // Puzzle reset notification
{"type": "NETWORK_HASHRATE", "total_hashrate": 456.78, "active_miners": 3, "timestamp": 1234567890.0}
```

**Network Hashrate Aggregation** (`state.py:267-327`):
- Clients report hashrate every few seconds via WebSocket
- Server aggregates all active miners' hashrates
- Broadcasts network statistics every 2 seconds
- Stale data (>10s old) automatically pruned
- Provides real-time visibility into mining competition

**Mining Time Tracking** (`state.py:76-123`):
- Only counts time when at least one miner is active
- Pauses timer when all miners disconnect
- Resumes when first miner reconnects
- Ensures accurate difficulty adjustment based on actual mining effort

### Frontend

- **Preact** + **Pico.css** for UI
- **hash-wasm** for client-side Argon2 computation
- **ThumbmarkJS** for device fingerprinting
- **Web Worker** (`worker.js`) for non-blocking hash computation

## Important Constraints

### Single-Process Requirement

**Why**: Python's `asyncio.Lock` and in-memory state are process-local. Multiple workers = multiple independent states = broken atomic guarantees.

**Never do this**:
```bash
uvicorn main:app --workers 4  # WRONG - breaks atomic lock
```

### Cloudflare Dependency

The system relies on Cloudflare Trace data for IP binding. For local development:
- `/api/dev/trace` provides a mock endpoint
- Set frontend to fetch from this endpoint instead of `/cdn-cgi/trace`

Production deployments should be behind Cloudflare CDN.

### Memory Requirements

Each Argon2 computation uses 64MB RAM (by design - this is the anti-farming mechanism). Concurrent miners on server-side verification can spike memory usage, but verification is fast (~100ms) due to the atomic lock.

## Configuration

### Environment Variables

All configuration parameters can be set via environment variables in `.env` file:

```bash
# ==================== Server Configuration ====================
PORT=8000  # Server port (default: 8000)

# ==================== Difficulty Settings ====================
HASHPASS_DIFFICULTY=3               # Initial difficulty (1-6)
HASHPASS_MIN_DIFFICULTY=1           # Minimum difficulty
HASHPASS_MAX_DIFFICULTY=6           # Maximum difficulty
HASHPASS_TARGET_TIME_MIN=30         # Min target solve time (seconds)
HASHPASS_TARGET_TIME_MAX=120        # Max target solve time (seconds)

# ==================== Argon2 Parameters ====================
HASHPASS_ARGON2_TIME_COST=3         # Iteration count
HASHPASS_ARGON2_MEMORY_COST=65536   # Memory in KB (64MB)
HASHPASS_ARGON2_PARALLELISM=1       # Thread count (keep at 1)

# ==================== Turnstile Configuration ====================
TURNSTILE_SITE_KEY=your_site_key_here
TURNSTILE_SECRET_KEY=your_secret_key_here
TURNSTILE_TEST_MODE=true            # Dev mode (auto-pass)

# ==================== Webhook (Optional) ====================
WEBHOOK_URL=https://your-domain.com/api/webhook
WEBHOOK_TOKEN=your_secret_token_here    # Bearer Token for authentication

# ==================== Performance ====================
HASHPASS_DISABLE_UVLOOP=false       # Disable uvloop (Linux/macOS)
```

⚠️ **Important**: Changes to Argon2 parameters must be synchronized with client-side code (static/app.js).

### Difficulty Adjustment

Difficulty automatically adjusts based on solve times:

Difficulty scaling:
- Difficulty 1: ~16 attempts average (~1 second)
- Difficulty 2: ~256 attempts (~15 seconds)
- Difficulty 3: ~4096 attempts (~1 minute)
- Difficulty 4: ~65536 attempts (~15 minutes)
- Difficulty 5: ~1M attempts (~4 hours)
- Difficulty 6: ~16M attempts (~64 hours)

**Automatic Adjustment Rules**:
- Solve time < `HASHPASS_TARGET_TIME_MIN`: Increase difficulty (if not at max)
- Solve time > `HASHPASS_TARGET_TIME_MAX`: Decrease difficulty (if not at min)
- No solution after `HASHPASS_TARGET_TIME_MAX` (mining time): Auto-decrease difficulty + reset puzzle

**Mining Time Tracking**:
- Only counts time when miners are actively mining
- Pauses when all miners disconnect
- Ensures fair difficulty adjustment based on actual mining effort

### Cloudflare Turnstile Configuration

**HashPass** integrates Cloudflare Turnstile for bot protection. All API endpoints (`/api/puzzle`, `/api/verify`) and WebSocket connections require valid Turnstile tokens.

#### Environment Variables

Create a `.env` file in the project root:

```bash
# Turnstile Configuration
TURNSTILE_SITE_KEY=your_site_key_here
TURNSTILE_SECRET_KEY=your_secret_key_here
TURNSTILE_TEST_MODE=false
```

**Get your keys**: https://dash.cloudflare.com/?to=/:account/turnstile

#### Test Mode (Development)

For local development without real Turnstile verification:

```bash
TURNSTILE_TEST_MODE=true
```

In test mode:
- Uses Cloudflare's test keys (`1x00000000000000000000AA`)
- All tokens automatically pass verification
- No actual API calls to Turnstile servers
- Widget still renders for UI testing

#### Production Mode

Set real keys in `.env`:

```bash
TURNSTILE_SITE_KEY=1x00000000000000000000AA  # Your actual site key
TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA  # Your actual secret key
TURNSTILE_TEST_MODE=false
```

#### Token Flow

1. **Frontend Initialization**:
   - Page loads → Turnstile Widget renders
   - User passes challenge → Token received
   - UI enabled + WebSocket connected

2. **API Request Protection**:
   - Client sends token in `Authorization: Bearer <token>` header
   - Server validates token with Cloudflare Siteverify API
   - Request rejected (403) if token invalid/missing

3. **WebSocket Protection**:
   - Token passed as query parameter: `ws://host/api/ws?token=<token>`
   - Connection rejected (1008 close code) if invalid
   - Frontend prompts user to refresh page

4. **Token Expiration**:
   - Tokens expire after 5 minutes
   - Widget automatically resets and requests new verification
   - UI disabled until new token obtained

#### Security Mechanisms

**What Turnstile adds**:
- Bot detection (prevents automated mining scripts)
- Rate limiting (Cloudflare's built-in protections)
- Challenge-response verification
- IP binding (validates token matches request origin)

**Integration Points**:
- `src/core/turnstile.py` - Token verification logic
- `src/api/routes.py` - Endpoint protection middleware
- `static/app.js` - Frontend token management
- `static/index.html` - Widget rendering

**Error Handling**:
- Missing token → 403 Forbidden
- Expired token → Widget auto-resets
- Invalid token → 403 Forbidden + logged
- WebSocket token fail → 1008 close code

### Webhook Notifications

**HashPass** supports asynchronous Webhook notifications to external services when users successfully obtain invite codes.

#### Configuration

Add the Webhook URL to your `.env` file:

```bash
# Webhook Configuration
WEBHOOK_URL=https://your-domain.com/api/webhook
```

Leave empty to disable Webhook functionality:

```bash
WEBHOOK_URL=
```

**Bearer Token Authentication (Optional)**:

For secure Webhook endpoints, configure a Bearer Token:

```bash
# Optional Bearer Token for Webhook authentication
WEBHOOK_TOKEN=your_secret_token_here
```

When `WEBHOOK_TOKEN` is set, the system will include it in the request header:

```
Authorization: Bearer your_secret_token_here
```

**Security Note**: Keep your `WEBHOOK_TOKEN` secret and never commit it to version control.

#### Webhook Payload

When a user wins an invite code, the system sends a POST request with the following JSON payload:

```json
{
  "visitor_id": "abc123def456...",
  "invite_code": "HASHPASS-XYZ789"
}
```

**Fields**:
- `visitor_id`: Device fingerprint (ThumbmarkJS ID)
- `invite_code`: Generated HMAC-derived invite code

#### Behavior

**Non-blocking**: Webhook requests are sent asynchronously using `asyncio.create_task()`, ensuring they do not delay the invite code response to the user.

**Timeout**: Webhook requests timeout after 5 seconds.

**Error Handling**: Failed webhooks are logged to console but do NOT affect invite code distribution. Users will receive their codes even if the webhook fails.

**Logs**: Check server logs for webhook status:
```
[Webhook] ✓ 发送成功 -> https://your-domain.com/api/webhook
[Webhook] Payload: {"visitor_id": "...", "invite_code": "..."}
```

Error logs:
```
[Webhook] ✗ 请求超时 (5s) -> https://your-domain.com/api/webhook
[Webhook] ✗ 网络请求失败: ConnectionError(...)
[Webhook] ✗ 服务器返回错误状态码: 500
```

#### Implementation Details

**Module**: `src/core/webhook.py`
**Integration Point**: `src/api/routes.py:117-123`
**Triggered**: After successful hash verification, before puzzle reset

#### Security Considerations

**Best Practices**:
- Use HTTPS endpoints in production (`https://...`)
- Configure `WEBHOOK_TOKEN` for Bearer Token authentication
- Implement token verification on your webhook receiver
- Validate payload structure before processing
- Rate limit webhook endpoint to prevent abuse

**Authentication Flow**:
1. Set `WEBHOOK_TOKEN` in your `.env` file
2. HashPass includes token in request header: `Authorization: Bearer <token>`
3. Your webhook endpoint validates the token
4. Reject requests with missing/invalid tokens (return 401/403)

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

**What Webhook receives**:
- Device fingerprint (can be used for duplicate detection)
- Invite code (can be stored in your database)

**What Webhook does NOT receive**:
- IP address (privacy protection)
- Hash/nonce values (unnecessary for invite code processing)
- Timestamp (add server-side if needed)

## API Endpoints

- `GET /api/puzzle` - Returns current seed, difficulty, memory_cost (requires Turnstile token)
- `POST /api/verify` - Submits solution, returns invite code or error (requires Turnstile token)
- `GET /api/turnstile/config` - Returns Turnstile Site Key and test mode status
- `GET /api/health` - Health check with current seed preview
- `GET /api/dev/trace` - Development-only Cloudflare Trace mock
- `WS /api/ws?token=<token>` - WebSocket for real-time puzzle reset notifications (requires Turnstile token in query param)

## Data Persistence & Audit Logs

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

**Log Rotation Mechanism** (`routes.py:18-61`):
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

## Testing Concurrent Behavior

1. Start server: `python main.py`
2. Open two browser tabs to `http://localhost:8000`
3. Click "Start Mining" in both tabs simultaneously
4. First tab to find a solution wins
5. Second tab should receive 409 error (seed changed)
6. If WebSocket is connected, second tab stops automatically

## Security Considerations

**What this system prevents**:
- **Automated bots** (Cloudflare Turnstile challenge)
- **GPU farms** (memory-hard algorithm)
- **Proxy/VPN cheating** (IP binding via TraceData + Turnstile)
- **Multi-accounting** (hardware fingerprinting + Turnstile)
- **Race conditions** (atomic lock)
- **Script-based attacks** (Turnstile bot detection)

**What this system does NOT prevent**:
- Determined attackers with matching IP ranges
- Browser fingerprint spoofing at engine level
- Users with high-memory systems having advantage (by design)

## Troubleshooting

**"Puzzle already solved" errors**: Normal behavior - someone else won first. Seed has reset.

**"Identity mismatch" errors**: Client's TraceData IP doesn't match server-detected IP. Check Cloudflare configuration or use `/api/dev/trace` for local dev.

**"Missing Turnstile token" errors**:
- Ensure `.env` file exists with `TURNSTILE_TEST_MODE=true` for development
- Check browser console for Turnstile Widget errors
- Verify Turnstile script loaded (check Network tab)
- Try refreshing the page to reinitialize Widget

**Turnstile Widget not rendering**:
- Check browser console for JavaScript errors
- Verify `https://challenges.cloudflare.com/turnstile/v0/api.js` is accessible
- Ensure no ad blockers are interfering
- Check `/api/turnstile/config` returns valid Site Key

**"403 Forbidden" on API requests**:
- Frontend: Check that `turnstileToken` is set before making requests
- Backend: Verify `TURNSTILE_TEST_MODE=true` in development
- Production: Confirm real Turnstile keys are set in environment

**WebSocket closes immediately (1008 code)**:
- Token missing or invalid in WebSocket URL
- Refresh page to get new Turnstile token
- Check server logs for validation errors

**Multiple workers warning**: If deploying with process managers (systemd, supervisor), ensure `--workers 1` is set.

**WebSocket not connecting**: Check CORS settings and ensure WebSocket endpoint is accessible. For production, use `wss://` (secure WebSocket).

**Difficulty not adjusting**:
- Check that miners are sending `mining_start`/`mining_stop` messages
- Verify mining time is being tracked (check server logs)
- Ensure `HASHPASS_MIN_DIFFICULTY` and `HASHPASS_MAX_DIFFICULTY` are set correctly
- Difficulty only adjusts after a puzzle is solved or times out

**Network hashrate shows 0**:
- Ensure frontend is sending `hashrate` messages via WebSocket
- Check that WebSocket connection is established before mining starts
- Verify `client_hashrates` dict is being populated (server-side debug)
- Hashrate data becomes stale after 10 seconds of no updates

**High memory usage**:
- ProcessPoolExecutor creates worker processes (each uses ~50-100MB base memory)
- Each Argon2 verification uses 64MB temporarily
- Consider reducing `HASHPASS_ARGON2_MEMORY_COST` for low-memory systems (but reduces anti-farming protection)
- Default worker count: CPU cores - 1 (can be reduced in `executor.py`)

**Slow verification times**:
- Check ProcessPoolExecutor is initialized (`[Executor] Process pool initialized` in logs)
- Verify system has enough CPU cores for worker processes
- High concurrent verification load may cause queuing
- Consider tuning `HASHPASS_ARGON2_TIME_COST` (lower = faster, but weaker anti-bot protection)
