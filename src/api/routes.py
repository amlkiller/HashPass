import asyncio
import json
import secrets
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from src.core.crypto import generate_invite_code, verify_argon2_solution
from src.core.executor import get_process_pool
from src.core.state import state
from src.core.turnstile import (
    get_turnstile_config,
    verify_turnstile_token,
)
from src.core.webhook import send_webhook_notification
from src.models.schemas import PuzzleResponse, Submission, VerifyResponse

router = APIRouter(prefix="/api")


async def append_to_verify_log(verify_data: dict) -> None:
    """
    异步追加验证数据到 verify.json（带日志轮转）
    此函数在锁外执行，避免阻塞其他验证请求

    日志轮转策略：
    - 每 1000 条记录创建新文件
    - 文件命名: verify_YYYYMMDD_HHMMSS.json
    - 主文件 verify.json 始终保持最新数据
    """
    try:
        verify_file = Path("verify.json")
        records = []

        # 读取现有记录
        if verify_file.exists():
            with open(verify_file, "r", encoding="utf-8") as f:
                records = json.load(f)

        # 检查是否需要轮转（达到 1000 条）
        if len(records) >= 1000:
            # 创建归档文件
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_file = Path(f"verify_{timestamp}.json")

            # 将旧记录移动到归档文件
            with open(archive_file, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)

            print(
                f"[Log Rotation] Archived {len(records)} records to {archive_file.name}"
            )

            # 清空主文件记录
            records = []

        # 追加新记录
        records.append(verify_data)

        # 写入主文件
        with open(verify_file, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"[File I/O Error] Failed to write verify.json: {e}")


@router.get("/puzzle", response_model=PuzzleResponse)
async def get_puzzle(request: Request):
    """
    获取当前谜题

    注意：此端点不直接验证 Turnstile Token。
    客户端应建立 WebSocket 连接（已验证 Turnstile）后调用此端点。
    """
    return PuzzleResponse(
        seed=state.current_seed,
        difficulty=state.difficulty,
        memory_cost=state.ph.memory_cost,
        time_cost=state.ph.time_cost,
        parallelism=state.ph.parallelism,
    )


@router.post("/verify", response_model=VerifyResponse)
async def verify_solution(sub: Submission, request: Request):
    """
    验证哈希解并分发邀请码

    注意：此端点不直接验证 Turnstile Token。
    客户端应建立 WebSocket 连接（已验证 Turnstile）后调用此端点。
    """

    # 1. 获取真实 IP（Cloudflare Header）
    real_ip = request.headers.get("cf-connecting-ip")
    if not real_ip:
        # 本地开发回退
        real_ip = request.client.host

    # 2. 反作弊：验证 TraceData 中的 IP 是否匹配
    if f"ip={real_ip}" not in sub.traceData:
        raise HTTPException(
            status_code=403,
            detail="Identity mismatch: TraceData IP doesn't match request IP",
        )

    # 3. 快速失败：在进入锁前检查 Seed（减少无效请求的锁等待时间）
    if state.current_seed != sub.submittedSeed:
        raise HTTPException(
            status_code=409, detail="Puzzle already solved by someone else"
        )

    # 4. 进入原子锁临界区
    async with state.lock:
        # 4.1 二次检查 Seed（Double-Check Locking）
        if state.current_seed != sub.submittedSeed:
            raise HTTPException(
                status_code=409, detail="Puzzle already solved by someone else"
            )

        # 4.2 计算解题耗时（只统计有矿工挖矿的时间）
        solve_time = state.get_current_mining_time()

        # 4.3 使用进程池验证哈希解（避免阻塞事件循环）
        loop = asyncio.get_running_loop()
        executor = get_process_pool()

        is_valid, error_message = await loop.run_in_executor(
            executor,
            verify_argon2_solution,
            sub.nonce,
            sub.submittedSeed,
            sub.visitorId,
            sub.traceData,
            sub.hash,
            state.difficulty,
            state.argon2_time_cost,
            state.argon2_memory_cost,
            state.argon2_parallelism,
        )

        if not is_valid:
            raise HTTPException(
                status_code=400, detail=error_message or "Invalid hash solution"
            )

        # 5. 获胜处理：使用 HMAC 派生邀请码并重置谜题
        invite_code = generate_invite_code(
            hmac_secret=state.hmac_secret,
            visitor_id=sub.visitorId,
            nonce=sub.nonce,
            seed=sub.submittedSeed,
        )

        # 5.1 异步发送 Webhook 通知（不阻塞响应）
        asyncio.create_task(
            send_webhook_notification(visitor_id=sub.visitorId, invite_code=invite_code)
        )

        # 5.2 动态难度调整
        old_difficulty, new_difficulty, reason = state.adjust_difficulty(solve_time)
        print(f"[Difficulty Adjustment] {reason}: {old_difficulty} -> {new_difficulty}")

        # 5.3 准备验证数据（在锁内）
        verify_data = {
            "timestamp": datetime.now().isoformat(),
            "invite_code": invite_code,
            "visitor_id": sub.visitorId,
            "nonce": sub.nonce,
            "hash": sub.hash,
            "seed": sub.submittedSeed,
            "real_ip": real_ip,
            "trace_data": sub.traceData,
            "difficulty": old_difficulty,
            "solve_time": round(solve_time, 2),
            "new_difficulty": new_difficulty,
            "adjustment_reason": reason,
        }

        # 5.4 重置puzzle
        state.reset_puzzle()

        # 6. 广播 puzzle 重置通知给所有连接的客户端
        await state.broadcast_puzzle_reset()

        # 7. 取消旧的超时任务并启动新的
        await state.start_timeout_checker()

    # 8. 异步写入验证日志（锁外执行，不阻塞响应）
    asyncio.create_task(append_to_verify_log(verify_data))

    return VerifyResponse(invite_code=invite_code)


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "current_seed": state.current_seed[:8] + "..."}


@router.get("/dev/trace")
async def dev_trace(request: Request):
    """开发模式：模拟 Cloudflare Trace 接口"""
    client_ip = request.client.host

    # 模拟 Cloudflare trace 格式
    trace_data = f"""fl=0f0
h=localhost
ip={client_ip}
ts={secrets.token_hex(8)}
visit_scheme=http
uag=Mozilla/5.0
colo=DEV
sliver=none
http=http/1.1
loc=CN
tls=off
sni=off
warp=off
gateway=off
rbi=off
kex=none"""

    return trace_data


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 连接端点 - 用于广播 puzzle 重置通知
    需要在 Query Parameter 中传递 Turnstile Token
    """
    # 1. 从 Query Parameter 获取 Token
    token = websocket.query_params.get("token")

    if not token:
        await websocket.close(
            code=1008, reason="Missing Turnstile token in query parameter"
        )
        return

    # 2. 获取客户端 IP
    real_ip = websocket.headers.get("cf-connecting-ip") or websocket.client.host

    # 3. 验证 Token
    is_valid, error_message = await verify_turnstile_token(token, real_ip)

    if not is_valid:
        print(f"[WebSocket] Token validation failed for IP {real_ip}: {error_message}")
        await websocket.close(
            code=1008, reason=error_message or "Invalid Turnstile token"
        )
        return

    # 4. Token 验证通过，接受连接
    await websocket.accept()
    state.active_connections.add(websocket)
    print(f"[WebSocket] New connection from IP {real_ip} (verified)")

    try:
        # 保持连接活跃，监听客户端消息（如心跳）
        while True:
            data = await websocket.receive_text()

            # 尝试解析 JSON 消息
            try:
                message_data = json.loads(data)
                msg_type = message_data.get("type")
            except (json.JSONDecodeError, AttributeError):
                # 兼容旧的纯文本 "ping" 消息
                if data == "ping":
                    msg_type = "ping"
                    message_data = {}
                else:
                    continue

            if msg_type == "ping":
                # 现有的心跳逻辑
                online_count = len(state.active_connections)
                pong_message = json.dumps({"type": "PONG", "online": online_count})
                await websocket.send_text(pong_message)

            elif msg_type == "mining_start":
                # 新增：矿工开始挖矿
                state.start_miner(websocket)

            elif msg_type == "mining_stop":
                # 新增：矿工停止挖矿
                state.stop_miner(websocket)

            elif msg_type == "hashrate":
                # 新增：处理算力报告
                payload = message_data.get("payload", {})
                rate = payload.get("rate", 0.0)

                # 验证算力值（防止恶意数据）
                if isinstance(rate, (int, float)) and 0 <= rate < 1_000:
                    await state.update_client_hashrate(websocket, rate, real_ip)
                else:
                    print(f"[WebSocket] 无效算力值来自 {real_ip}: {rate}")

    except WebSocketDisconnect:
        state.active_connections.discard(websocket)
        await state.remove_client_hashrate(websocket)
        state.stop_miner(websocket)  # 断开连接时停止挖矿计时
        print(f"[WebSocket] Client disconnected: {real_ip}")
    except Exception as e:
        state.active_connections.discard(websocket)
        await state.remove_client_hashrate(websocket)
        state.stop_miner(websocket)  # 异常断开时也停止挖矿计时
        print(f"[WebSocket] Error: {e}")


@router.get("/turnstile/config")
async def get_turnstile_site_key():
    """
    获取 Turnstile Site Key（前端需要）

    仅返回 Site Key，不暴露 Secret Key
    """
    site_key, _, test_mode = get_turnstile_config()
    return {"siteKey": site_key, "testMode": test_mode}
