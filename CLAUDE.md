# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**HashPass** is an invite code distribution system based on Client Puzzles architecture. It uses **Argon2d memory-hard proof-of-work** with an **in-memory atomic lock** to create a fair, race-based invite code system that:

- Requires no database (pure in-memory state)
- Uses `asyncio.Lock` for atomic puzzle seed management
- Prevents GPU/ASIC farming via memory-hard hashing (64MB+ per computation)
- Binds computations to IP addresses via Cloudflare Trace data
- Uses hardware fingerprinting (ThumbmarkJS) to prevent multi-account abuse
- Provides a real-time admin dashboard for system monitoring and control

### Core Concept

The system maintains a single global puzzle seed in memory. When a user solves the puzzle (finds a hash with N leading zero bits), they win the invite code and the seed immediately resets, invalidating all other users' work in progress.

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

**CRITICAL**: Must run with `--workers 1` (single process mode). Multi-worker deployments break the atomic lock mechanism since each process has its own memory space.

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

## Architecture

### Directory Structure

```
main.py                        # Entry point, FastAPI app, middleware, lifespan
src/
  api/
    routes.py                  # Public API (/puzzle, /verify, /ws, /turnstile/config, /health, /dev/trace)
    admin.py                   # Admin API (/admin/status, /admin/difficulty, /admin/kick, etc.)
  core/
    state.py                   # Global SystemState singleton (lock, seed, difficulty, sessions, miners)
    crypto.py                  # Argon2 verification & HMAC invite code generation
    turnstile.py               # Cloudflare Turnstile token verification
    webhook.py                 # Async webhook notification on win
    executor.py                # ProcessPoolExecutor for CPU-intensive Argon2 verification
    event_loop.py              # uvloop initialization (Linux/macOS)
    useragent.py               # User-Agent validation (block bots/curl/wget)
    admin_auth.py              # Admin Bearer token authentication
    log_config.py              # Logging configuration with file-locked handlers
  models/
    schemas.py                 # Pydantic models (public + admin)
static/
  index.html                   # Main mining UI
  app.js                       # Frontend entry point
  worker.js                    # Web Worker for Argon2 computation
  js/
    state.js                   # Global frontend state
    mining.js                  # Mining orchestration (multi-worker)
    websocket.js               # WebSocket client (reconnection, Session Token)
    turnstile.js               # Turnstile widget management
    hashrate.js                # Hashrate display (local + network)
    logger.js                  # Log panel with smart highlighting
    theme.js                   # Light/Dark/System theme switcher
    utils.js                   # Formatting helpers
  css/
    custom.css                 # Custom CSS variables and styles
  admin.html                   # Admin dashboard page
  admin/
    app.js                     # Admin entry point
    css/admin.css              # Admin-specific styles
    js/
      state.js                 # Admin state management
      api.js                   # Admin API client
      websocket.js             # Admin WebSocket (real-time status)
      dashboard.js             # Dashboard tab (metrics, graphs)
      params.js                # Parameters tab (difficulty, Argon2, workers)
      logs.js                  # Logs tab (paginated, searchable)
      operations.js            # Operations tab (kick, ban, reset)
```

### Key Components

#### 1. Global State (`src/core/state.py`)

The `SystemState` singleton manages all in-memory state:

- **Puzzle state**: `current_seed`, `difficulty`, `min/max_difficulty`, `target_time_min/max`
- **Atomic lock**: `asyncio.Lock` for serial verification
- **Argon2 config**: `argon2_time_cost`, `argon2_memory_cost`, `argon2_parallelism`, `worker_count`
- **HMAC secret**: 256-bit key for invite code derivation (regenerates on restart)
- **Mining tracking**: `active_miners` set, `total_mining_time`, `is_mining_active` (pauses when no miners connected)
- **WebSocket connections**: `active_connections` set for broadcasting
- **Session Tokens**: `session_tokens` dict mapping token -> {websocket, ip, created_at, is_connected, disconnected_at}
- **Client hashrates**: `client_hashrates` dict for network statistics aggregation
- **IP blacklist**: `banned_ips` set (in-memory, clears on restart)
- **Admin connections**: `admin_connections` set for admin WebSocket
- **Background tasks**: `timeout_task`, `aggregation_task` (5s interval), `cleanup_task` (60s interval)

#### 2. Authentication & Session Flow

HashPass uses a two-tier token system:

1. **Turnstile Token** (single-use): Verified once on initial WebSocket connection
2. **Session Token** (persistent): Generated by server after Turnstile verification, bound to IP, 5-minute expiry after disconnect

**Flow**:
1. Page loads -> Turnstile widget renders -> user passes challenge -> token received
2. Frontend connects WebSocket with Turnstile token: `/api/ws?token=<turnstile_token>`
3. Server validates Turnstile token once, generates Session Token, sends it back via WebSocket JSON message `{"type": "SESSION_TOKEN", "token": "..."}`
4. Frontend stores Session Token, uses it as `Authorization: Bearer <token>` for API requests (`/api/puzzle`, `/api/verify`)
5. On WebSocket disconnect, Session Token is marked as disconnected (not deleted)
6. On reconnect, frontend connects with Session Token: `/api/ws?token=<session_token>` - server validates and reactivates
7. Disconnected tokens expire after 5 minutes, cleaned up by background task

#### 3. Proof-of-Work System

**Client-side** (static/worker.js):
1. Get device fingerprint via ThumbmarkJS
2. Fetch Cloudflare Trace data (IP binding)
3. Fetch puzzle from `/api/puzzle` (with Session Token header)
4. Spawn N Web Workers (configurable `worker_count` from server)
5. Each worker: `Hash = Argon2d(nonce.toString(), salt=seed+fingerprint+traceData)`
6. Workers use stride pattern (nonce += workerCount) to avoid overlap
7. Find nonce where hash has N leading zero bits
8. Submit to `/api/verify` (with Session Token header)

**Server-side** (src/api/routes.py `verify_solution`):
1. Validate Session Token (IP binding check)
2. Check IP blacklist
3. Verify TraceData IP matches request IP
4. Fast-fail if seed changed (before lock)
5. Enter atomic lock critical section
6. Double-check seed (DCL pattern)
7. Calculate solve time (mining time only)
8. Verify Argon2 hash via ProcessPoolExecutor (non-blocking)
9. Generate HMAC-derived invite code
10. Send async webhook notification
11. Adjust difficulty based on solve time
12. Reset puzzle + broadcast PUZZLE_RESET to all clients
13. Restart timeout checker
14. Async write to verify.json log (outside lock)

#### 4. Dynamic Difficulty

Uses a proportional step algorithm based on `log2(target_midpoint / solve_time)`:
- Each +1 bit = 2x harder, each -1 bit = 2x easier
- Steps clamped to [-4, +4] range per adjustment
- Timeout auto-decreases by at least 2 bits
- Mining time only counts when miners are actively connected

#### 5. Process Pool Executor (`src/core/executor.py`)

Prevents Argon2 verification from blocking the asyncio event loop:
- `ProcessPoolExecutor` with `cpu_count - 1` workers (bypasses GIL)
- Initialized at startup via `init_process_pool()`, shutdown on exit
- Used in routes.py: `await loop.run_in_executor(executor, verify_argon2_solution, ...)`

#### 6. Middleware (`main.py`)

- **SecurityHeadersMiddleware**: Adds CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy to all responses
- **UserAgentMiddleware**: Blocks non-browser clients (curl, wget, Python, Node, bots) on `/api/` routes. Exempts `/api/health`, `/api/dev/trace`, and `/api/admin/*`

#### 7. Frontend Architecture

- **Tailwind CSS** (CDN) + **Pico.css** + custom CSS variables for styling
- **hash-wasm** (WASM) for client-side Argon2 computation
- **ThumbmarkJS** for device fingerprinting
- **Web Workers** for non-blocking mining (multi-worker parallelism)
- **ES Modules** with import maps for dependency management
- Theme system: Light/Dark/System with localStorage persistence

## API Endpoints

### Public

| Endpoint | Auth | Description |
|---|---|---|
| `GET /api/puzzle` | Session Token | Returns seed, difficulty, Argon2 params, worker_count |
| `POST /api/verify` | Session Token | Submits solution, returns invite code |
| `WS /api/ws?token=<token>` | Turnstile or Session Token | Real-time puzzle resets + network stats |
| `GET /api/turnstile/config` | None | Returns Turnstile Site Key and test mode |
| `GET /api/health` | None | Health check with seed preview |
| `GET /api/dev/trace` | None | Mock Cloudflare Trace for local dev |

### Admin (all require `Authorization: Bearer <ADMIN_TOKEN>`)

| Endpoint | Description |
|---|---|
| `GET /api/admin/status` | Full system state snapshot |
| `GET /api/admin/miners` | Active miners with hashrates |
| `GET /api/admin/sessions` | Session Token list |
| `GET /api/admin/logs` | Paginated logs (search, file selection) |
| `GET /api/admin/logs/stats` | Aggregate statistics |
| `POST /api/admin/difficulty` | Adjust difficulty params (resets puzzle) |
| `POST /api/admin/target-time` | Adjust target time window (resets puzzle) |
| `POST /api/admin/argon2` | Adjust Argon2 params (resets puzzle) |
| `POST /api/admin/worker-count` | Set frontend worker count (resets puzzle) |
| `POST /api/admin/reset-puzzle` | Force puzzle reset |
| `POST /api/admin/kick-all` | Disconnect all + revoke all tokens |
| `POST /api/admin/kick` | Ban IP + kick + revoke tokens |
| `POST /api/admin/unban` | Remove IP from blacklist |
| `GET /api/admin/blacklist` | View banned IPs |
| `POST /api/admin/clear-sessions` | Clear all Session Tokens |
| `POST /api/admin/regenerate-hmac` | Regenerate HMAC secret |
| `WS /api/admin/ws?token=<admin_token>` | Real-time status updates (every 2s) |

### WebSocket Protocol

**Client -> Server**:
```json
{"type": "ping"}
{"type": "mining_start"}
{"type": "mining_stop"}
{"type": "hashrate", "payload": {"rate": 123.45}}
```

**Server -> Client**:
```json
{"type": "SESSION_TOKEN", "token": "..."}
{"type": "PONG", "online": 5}
{"type": "PUZZLE_RESET", "seed": "abc...", "difficulty": 12}
{"type": "NETWORK_HASHRATE", "total_hashrate": 456.78, "active_miners": 3, "timestamp": ...}
```

## Configuration

### Environment Variables (`.env`)

```bash
# Server
PORT=8000
ADMIN_TOKEN=your_admin_token_here

# Difficulty
HASHPASS_DIFFICULTY=1              # Initial difficulty (leading zero bits)
HASHPASS_MIN_DIFFICULTY=1
HASHPASS_MAX_DIFFICULTY=6
HASHPASS_TARGET_TIME_MIN=30        # seconds
HASHPASS_TARGET_TIME_MAX=120       # seconds

# Argon2
HASHPASS_ARGON2_TIME_COST=3
HASHPASS_ARGON2_MEMORY_COST=65536  # KB (64MB)
HASHPASS_ARGON2_PARALLELISM=1
HASHPASS_WORKER_COUNT=1            # Frontend worker count
HASHPASS_MAX_NONCE_SPEED=0         # Max nonce/s (0 = disabled)

# Turnstile
TURNSTILE_SITE_KEY=your_site_key_here
TURNSTILE_SECRET_KEY=your_secret_key_here
TURNSTILE_TEST_MODE=true           # true for dev, false for production

# Webhook (optional)
WEBHOOK_URL=
WEBHOOK_TOKEN=

# Performance
HASHPASS_DISABLE_UVLOOP=false
```

Argon2 parameter changes must be synchronized between server and client (server provides params via `/api/puzzle`, client uses them in worker.js).

### uvloop (Linux/macOS)

Automatically installed at startup if available. Provides ~30-40% faster WebSocket broadcasting. Disable with `HASHPASS_DISABLE_UVLOOP=true`.

## Data Persistence

### Audit Logs

All successful verifications logged to `verify.json` with automatic rotation at 1000 records (archived to `verify_YYYYMMDD_HHMMSS.json`). Logging is async and non-blocking.

**Log entry fields**: timestamp, invite_code, visitor_id, nonce, hash, seed, real_ip, trace_data, difficulty, solve_time, new_difficulty, adjustment_reason.

**File locking**: Both `verify.json` and `log/hashpass.log` use cross-platform file locks to prevent concurrent write conflicts:
- Windows: `msvcrt.locking` (locks first byte of file)
- Unix/Linux/macOS: `fcntl.flock` (exclusive lock)
- Verification logs use a separate lock file (`verify.json.lock`) to coordinate writes
- Application logs use `LockedTimedRotatingFileHandler` with built-in file locking
- All locks are blocking and automatically released after write completion

## Important Constraints

### Single-Process Requirement

`asyncio.Lock` and in-memory state are process-local. Multiple workers = multiple independent states = broken atomic guarantees. Always use `--workers 1`.

### Cloudflare Dependency

The system relies on Cloudflare Trace data for IP binding. For local development, `/api/dev/trace` provides a mock endpoint.

### Memory Requirements

Each Argon2 computation uses 64MB RAM (by design). ProcessPoolExecutor workers add ~50-100MB each base memory.

## Security

**Prevents**: Automated bots (Turnstile + UA filtering), GPU farms (memory-hard Argon2), proxy attacks (IP binding via TraceData), multi-accounting (device fingerprinting), race conditions (atomic lock), token replay (Session Tokens bound to IP with expiry), script-based attacks (User-Agent validation).

**Does not prevent**: Attackers with matching IP ranges, browser fingerprint spoofing at engine level, users with high-memory systems (by design).

## Pydantic Models (`src/models/schemas.py`)

- `PuzzleResponse`: seed, difficulty, memory_cost, time_cost, parallelism, worker_count
- `Submission`: visitorId, nonce, submittedSeed, traceData, hash
- `VerifyResponse`: invite_code
- `AdminDifficultyUpdate`: difficulty?, min_difficulty?, max_difficulty?
- `AdminTargetTimeUpdate`: target_time_min?, target_time_max?
- `AdminArgon2Update`: time_cost?, memory_cost?, parallelism?
- `AdminWorkerCountUpdate`: worker_count
- `AdminKickRequest`: ip
- `AdminUnbanRequest`: ip

## Troubleshooting

- **"Puzzle already solved" (409)**: Normal - someone else won first
- **"Identity mismatch" (403)**: TraceData IP doesn't match request IP; check Cloudflare config or use `/api/dev/trace`
- **"Invalid or expired session token" (401)**: Session Token expired or IP changed; refresh page
- **WebSocket closes with 1008**: Token invalid/expired/banned; refresh page
- **Difficulty not adjusting**: Check miners send `mining_start`/`mining_stop` messages; check min/max bounds
- **Network hashrate shows 0**: Ensure frontend sends `hashrate` messages via WebSocket; data becomes stale after 10s
- **High memory usage**: ProcessPoolExecutor workers + Argon2 64MB per verification; reduce `HASHPASS_ARGON2_MEMORY_COST` or worker count if needed
