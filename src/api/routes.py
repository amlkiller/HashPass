import asyncio
import json
import logging
import secrets
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket, WebSocketDisconnect

from src.core.crypto import generate_invite_code, verify_argon2_solution
from src.core.executor import get_process_pool
from src.core.state import state
from src.core.turnstile import (
    get_turnstile_config,
    verify_turnstile_token,
)
from src.core.webhook import send_webhook_notification
from src.core.useragent import validate_user_agent
from src.models.schemas import PuzzleResponse, Submission, VerifyResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ===== Session Token 验证依赖 =====
async def verify_session_token(
    authorization: str = Header(None),
    request: Request = None
) -> str:
    """
    验证 Session Token 的 FastAPI 依赖函数

    验证逻辑：
    1. 检查 Authorization Header 是否存在
    2. 验证格式是否为 "Bearer <token>"
    3. 验证 Token 是否有效
    4. 验证请求 IP 与 Token 绑定的 IP 是否一致

    Returns:
        验证通过的 Token 字符串

    Raises:
        HTTPException: 401 如果验证失败
    """
    # 1. 检查 Header 是否存在
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header"
        )

    # 2. 验证格式
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header format (expected 'Bearer <token>')"
        )

    # 3. 提取 Token
    token = authorization.replace("Bearer ", "", 1)

    # 4. 获取请求 IP
    real_ip = request.headers.get("cf-connecting-ip") or request.client.host

    # 5. 验证 Token 有效性和 IP 一致性
    if not state.validate_session_token(token, real_ip):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session token"
        )

    return token
# ===== 依赖函数结束 =====


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

            logger.info(
                "Log rotation: archived %d records to %s",
                len(records), archive_file.name,
            )

            # 清空主文件记录
            records = []

        # 追加新记录
        records.append(verify_data)

        # 写入主文件
        with open(verify_file, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error("Failed to write verify.json: %s", e, exc_info=True)


@router.get("/puzzle", response_model=PuzzleResponse)
async def get_puzzle(
    request: Request,
    token: str = Depends(verify_session_token)  # ← 新增：Token 验证
):
    """
    获取当前谜题

    注意：此端点需要有效的 Session Token。
    客户端应建立 WebSocket 连接后获取 Token，再调用此端点。
    """
    # 黑名单检查
    real_ip = request.headers.get("cf-connecting-ip") or request.client.host
    if state.is_banned(real_ip):
        raise HTTPException(status_code=403, detail="Access denied")

    return PuzzleResponse(
        seed=state.current_seed,
        difficulty=state.difficulty,
        memory_cost=state.ph.memory_cost,
        time_cost=state.ph.time_cost,
        parallelism=state.ph.parallelism,
        worker_count=state.worker_count,
        puzzle_start_time=state.puzzle_start_time,
        last_solve_time=state.last_solve_time,
        average_solve_time=round(sum(state.solve_history) / len(state.solve_history), 2) if state.solve_history else None,
    )


def check_nonce_speed(nonce: int, solve_time: float) -> tuple[bool, str]:
    """
    检查 nonce 计算速度是否超过阈值（nonce / solve_time）

    Args:
        nonce: 客户端提交的 nonce 值（尝试次数）
        solve_time: 解题耗时（秒）

    Returns:
        (True, "") 如果通过检查，(False, 错误信息) 如果超速
    """
    max_speed = state.max_nonce_speed

    if max_speed <= 0:
        return True, ""  # 未配置阈值，禁用检查

    if solve_time <= 0:
        return True, ""  # 无法计算速度，跳过检查

    speed = nonce / solve_time

    if speed > max_speed:
        return False, (
            f"Computation speed too high: {speed:.1f} nonce/s "
            f"(limit: {max_speed:.1f} nonce/s)"
        )

    return True, ""


@router.post("/verify", response_model=VerifyResponse)
async def verify_solution(
    sub: Submission,
    request: Request,
    token: str = Depends(verify_session_token)  # ← 新增：Token 验证
):
    """
    验证哈希解并分发邀请码

    注意：此端点需要有效的 Session Token。
    客户端应建立 WebSocket 连接后获取 Token，再调用此端点。
    """

    # 1. 获取真实 IP（Cloudflare Header）
    real_ip = request.headers.get("cf-connecting-ip")
    if not real_ip:
        # 本地开发回退
        real_ip = request.client.host

    # 1.1 黑名单检查
    if state.is_banned(real_ip):
        raise HTTPException(status_code=403, detail="Access denied")

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

        # 4.3 检查计算速度（nonce / solve_time）是否超过阈值
        speed_ok, speed_error = check_nonce_speed(sub.nonce, solve_time)
        if not speed_ok:
            logger.warning("Speed check failed for IP %s: %s", real_ip, speed_error)
            raise HTTPException(status_code=400, detail=speed_error)

        # 4.4 使用进程池验证哈希解（避免阻塞事件循环）
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
        state.record_solve_time(solve_time)
        logger.info("Difficulty adjustment: %s: %d -> %d", reason, old_difficulty, new_difficulty)

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
    支持两种认证方式：
    1. 首次连接：使用 Turnstile Token (query param: token)
    2. 重连：使用 Session Token (query param: token)
    """
    # 0. User-Agent 检查（BaseHTTPMiddleware 不拦截 WebSocket）
    ua = websocket.headers.get("user-agent")
    is_valid_ua, ua_reason = validate_user_agent(ua)
    if not is_valid_ua:
        logger.warning("WebSocket rejected: %s | ua=%r", ua_reason, ua)
        await websocket.close(code=1008, reason=ua_reason)
        return

    # 1. 从 Query Parameter 获取 Token
    token = websocket.query_params.get("token")

    if not token:
        await websocket.close(
            code=1008, reason="Missing token in query parameter"
        )
        return

    # 2. 获取客户端 IP
    real_ip = websocket.headers.get("cf-connecting-ip") or websocket.client.host

    # 2.1 黑名单检查
    if state.is_banned(real_ip):
        logger.warning("WebSocket rejected for banned IP: %s", real_ip)
        await websocket.close(code=1008, reason="Access denied")
        return

    # 3. 验证 Token (优先验证 Session Token，失败则验证 Turnstile Token)
    is_session_token = state.validate_session_token(token, real_ip)

    if is_session_token:
        # Session Token 验证成功，重连场景
        logger.info("WebSocket reconnecting with Session Token from IP %s", real_ip)

        # 重连豁免：踢掉旧的同 IP 连接
        old_ws = state.get_ip_connection(real_ip)
        if old_ws is not None:
            try:
                state.active_connections.discard(old_ws)
                await state.remove_client_hashrate(old_ws)
                state.stop_miner(old_ws)
                state.unregister_ip_connection(real_ip, old_ws)
                await old_ws.close(code=1008, reason="Replaced by new connection")
            except Exception:
                pass
            logger.info("Kicked old connection for IP %s (Session Token reconnect)", real_ip)

        # 接受连接
        await websocket.accept()
        state.active_connections.add(websocket)
        state.register_ip_connection(real_ip, websocket)

        # 重新激活 Token（更新 WebSocket 引用和连接状态）
        state.reconnect_session_token(token, websocket)
        logger.info("WebSocket reconnected successfully using existing Session Token")

    else:
        # 首次连接：不允许同 IP 多开
        if state.has_active_connection(real_ip):
            logger.warning("WebSocket rejected: duplicate IP %s", real_ip)
            await websocket.close(code=1008, reason="Duplicate connection from same IP")
            return

        # 尝试验证 Turnstile Token（首次连接场景）
        is_valid, error_message = await verify_turnstile_token(token, real_ip)

        if not is_valid:
            logger.warning("WebSocket token validation failed for IP %s: %s", real_ip, error_message)
            await websocket.close(
                code=1008, reason=error_message or "Invalid token"
            )
            return

        logger.info("WebSocket new connection from IP %s (Turnstile verified)", real_ip)

        # 接受连接
        await websocket.accept()
        state.active_connections.add(websocket)
        state.register_ip_connection(real_ip, websocket)

        # 生成并下发 Session Token（仅在首次连接时生成新的）
        session_token = state.generate_session_token(websocket, real_ip)
        await websocket.send_json({
            "type": "SESSION_TOKEN",
            "token": session_token
        })
        logger.info("Session Token sent to %s", real_ip)

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
                    logger.warning("Invalid hashrate from %s: %s", real_ip, rate)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", real_ip)
    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)
    finally:
        # ===== 关键修复：确保所有退出路径都清理资源 =====
        # 无论是正常断开、异常还是其他情况，都必须清理连接
        state.active_connections.discard(websocket)
        await state.remove_client_hashrate(websocket)
        state.stop_miner(websocket)  # 停止挖矿计时
        state.revoke_session_token(websocket)  # 清理 Session Token
        state.unregister_ip_connection(real_ip, websocket)  # 移除 IP 连接映射
        logger.info("WebSocket connection cleaned up for %s", real_ip)


@router.get("/turnstile/config")
async def get_turnstile_site_key():
    """
    获取 Turnstile Site Key（前端需要）

    仅返回 Site Key，不暴露 Secret Key
    """
    site_key, _, test_mode = get_turnstile_config()
    return {"siteKey": site_key, "testMode": test_mode}
