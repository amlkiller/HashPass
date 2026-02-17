import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from typing import Optional

from argon2 import PasswordHasher, Type
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from src.core.admin_auth import require_admin
from src.core.state import state
from src.models.schemas import (
    AdminArgon2Update,
    AdminDifficultyUpdate,
    AdminHmacUpdate,
    AdminKickRequest,
    AdminTargetTimeUpdate,
    AdminUnbanRequest,
    AdminWorkerCountUpdate,
)

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


# ===== 监控端点 =====


@admin_router.get("/status")
async def get_status(_: str = Depends(require_admin)):
    """系统全量状态快照"""
    return state.get_status_snapshot()


@admin_router.get("/miners")
async def get_miners(_: str = Depends(require_admin)):
    """矿工列表"""
    return state.get_miners_info()


@admin_router.get("/sessions")
async def get_sessions(_: str = Depends(require_admin)):
    """Session Token 列表"""
    return state.get_sessions_info()


def _list_log_files() -> list[str]:
    """列出所有验证日志文件名"""
    files = ["verify.json"]
    for p in sorted(Path(".").glob("verify_*.json"), reverse=True):
        files.append(p.name)
    return files


@admin_router.get("/logs")
async def get_logs(
    _: str = Depends(require_admin),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    file: str = Query("verify.json"),
):
    """验证日志（分页 + 搜索 + 文件选择）"""
    # 校验文件名防路径穿越
    allowed_files = _list_log_files()
    if file not in allowed_files:
        return {"records": [], "total": 0, "page": page, "pages": 0, "files": allowed_files}

    log_path = Path(file)
    records = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                records = json.load(f)
        except (json.JSONDecodeError, IOError):
            records = []

    # 搜索过滤
    if search:
        search_lower = search.lower()
        records = [
            r for r in records
            if search_lower in json.dumps(r, ensure_ascii=False).lower()
        ]

    # 按时间倒序
    records.reverse()

    total = len(records)
    pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    end = start + per_page

    return {
        "records": records[start:end],
        "total": total,
        "page": page,
        "pages": pages,
        "files": allowed_files,
    }


@admin_router.get("/logs/stats")
async def get_log_stats(_: str = Depends(require_admin)):
    """日志统计"""
    all_records = []

    # 收集所有日志文件的记录
    for file_name in _list_log_files():
        log_path = Path(file_name)
        if log_path.exists():
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    all_records.extend(json.load(f))
            except (json.JSONDecodeError, IOError):
                pass

    total_codes = len(all_records)
    solve_times = [r.get("solve_time", 0) for r in all_records if r.get("solve_time")]
    difficulties = [r.get("difficulty", 0) for r in all_records if r.get("difficulty")]
    unique_visitors = len(set(r.get("visitor_id", "") for r in all_records))

    avg_solve_time = sum(solve_times) / len(solve_times) if solve_times else 0
    sorted_times = sorted(solve_times)
    median_solve_time = sorted_times[len(sorted_times) // 2] if sorted_times else 0

    # 难度分布
    difficulty_dist = {}
    for d in difficulties:
        difficulty_dist[str(d)] = difficulty_dist.get(str(d), 0) + 1

    return {
        "total_codes": total_codes,
        "unique_visitors": unique_visitors,
        "avg_solve_time": round(avg_solve_time, 2),
        "median_solve_time": round(median_solve_time, 2),
        "difficulty_distribution": difficulty_dist,
    }


# ===== 参数调整端点 =====


@admin_router.post("/difficulty")
async def update_difficulty(
    body: AdminDifficultyUpdate,
    _: str = Depends(require_admin),
):
    """修改难度参数"""
    if body.min_difficulty is not None:
        if body.min_difficulty < 1 or body.min_difficulty > 32:
            return {"error": "min_difficulty must be between 1 and 32"}
        state.min_difficulty = body.min_difficulty

    if body.max_difficulty is not None:
        if body.max_difficulty < 1 or body.max_difficulty > 32:
            return {"error": "max_difficulty must be between 1 and 32"}
        state.max_difficulty = body.max_difficulty

    if state.min_difficulty > state.max_difficulty:
        state.min_difficulty, state.max_difficulty = state.max_difficulty, state.min_difficulty

    if body.difficulty is not None:
        if body.difficulty < state.min_difficulty or body.difficulty > state.max_difficulty:
            return {"error": f"difficulty must be between {state.min_difficulty} and {state.max_difficulty}"}
        state.difficulty = body.difficulty

    # 修改参数后立刻重置题目
    async with state.lock:
        state.reset_puzzle()
        await state.broadcast_puzzle_reset()
        await state.start_timeout_checker()

    logger.info(
        "Difficulty updated: %d (range: %d-%d) - puzzle reset",
        state.difficulty, state.min_difficulty, state.max_difficulty,
    )
    return {
        "difficulty": state.difficulty,
        "min_difficulty": state.min_difficulty,
        "max_difficulty": state.max_difficulty,
        "new_seed": state.current_seed[:8] + "...",
    }


@admin_router.post("/target-time")
async def update_target_time(
    body: AdminTargetTimeUpdate,
    _: str = Depends(require_admin),
):
    """修改目标时间"""
    if body.target_time_min is not None:
        if body.target_time_min < 1:
            return {"error": "target_time_min must be >= 1"}
        state.target_time_min = body.target_time_min

    if body.target_time_max is not None:
        if body.target_time_max < 1:
            return {"error": "target_time_max must be >= 1"}
        state.target_time_max = body.target_time_max

    if state.target_time_min > state.target_time_max:
        state.target_time_min, state.target_time_max = state.target_time_max, state.target_time_min

    # 修改参数后立刻重置题目
    async with state.lock:
        state.reset_puzzle()
        await state.broadcast_puzzle_reset()
        await state.start_timeout_checker()

    logger.info(
        "Target time updated: %d-%ds - puzzle reset",
        state.target_time_min, state.target_time_max,
    )
    return {
        "target_time_min": state.target_time_min,
        "target_time_max": state.target_time_max,
        "new_seed": state.current_seed[:8] + "...",
    }


@admin_router.post("/argon2")
async def update_argon2(
    body: AdminArgon2Update,
    _: str = Depends(require_admin),
):
    """修改 Argon2 参数（重建 PasswordHasher）"""
    if body.time_cost is not None:
        if body.time_cost < 1 or body.time_cost > 10:
            return {"error": "time_cost must be between 1 and 10"}
        state.argon2_time_cost = body.time_cost

    if body.memory_cost is not None:
        if body.memory_cost < 1024 or body.memory_cost > 1048576:
            return {"error": "memory_cost must be between 1024 and 1048576 KB"}
        state.argon2_memory_cost = body.memory_cost

    if body.parallelism is not None:
        if body.parallelism < 1 or body.parallelism > 8:
            return {"error": "parallelism must be between 1 and 8"}
        state.argon2_parallelism = body.parallelism

    # 重建 PasswordHasher
    state.ph = PasswordHasher(
        time_cost=state.argon2_time_cost,
        memory_cost=state.argon2_memory_cost,
        parallelism=state.argon2_parallelism,
        hash_len=32,
        type=Type.D,
    )

    # 修改参数后立刻重置题目
    async with state.lock:
        state.reset_puzzle()
        await state.broadcast_puzzle_reset()
        await state.start_timeout_checker()

    logger.info(
        "Argon2 params updated: time=%d, mem=%dKB, par=%d - puzzle reset",
        state.argon2_time_cost, state.argon2_memory_cost, state.argon2_parallelism,
    )
    return {
        "time_cost": state.argon2_time_cost,
        "memory_cost": state.argon2_memory_cost,
        "parallelism": state.argon2_parallelism,
        "new_seed": state.current_seed[:8] + "...",
    }


@admin_router.post("/worker-count")
async def update_worker_count(
    body: AdminWorkerCountUpdate,
    _: str = Depends(require_admin),
):
    """修改前端 Worker 数量"""
    if body.worker_count < 1 or body.worker_count > 32:
        return {"error": "worker_count must be between 1 and 32"}

    state.worker_count = body.worker_count

    # 修改参数后立刻重置题目
    async with state.lock:
        state.reset_puzzle()
        await state.broadcast_puzzle_reset()
        await state.start_timeout_checker()

    logger.info("Worker count updated: %d - puzzle reset", state.worker_count)
    return {
        "worker_count": state.worker_count,
        "new_seed": state.current_seed[:8] + "...",
    }


# ===== 手动操作端点 =====


@admin_router.post("/reset-puzzle")
async def reset_puzzle(_: str = Depends(require_admin)):
    """强制重置谜题"""
    async with state.lock:
        old_seed = state.current_seed[:8]
        state.reset_puzzle()
        await state.broadcast_puzzle_reset()
        await state.start_timeout_checker()

    logger.info("Puzzle force-reset (old seed: %s...)", old_seed)
    return {"message": "Puzzle reset", "new_seed": state.current_seed[:8] + "..."}


@admin_router.post("/kick-all")
async def kick_all(_: str = Depends(require_admin)):
    """断开所有矿工 WebSocket 连接并吊销所有 Session Token"""
    # 1. 先吊销所有 Token（阻止前端重连时通过 validate 校验）
    revoked = state.revoke_all_tokens()

    # 2. 再关闭 WebSocket（此时前端重连会被 validate 拒绝）
    connections = list(state.active_connections)
    count = len(connections)

    for ws in connections:
        try:
            await ws.close(code=1000, reason="Kicked by admin")
        except Exception:
            pass

    state.active_connections.clear()
    state.active_miners.clear()
    state.client_hashrates.clear()

    logger.info("Kicked all miners (%d connections, %d sessions revoked)", count, revoked)
    return {"message": f"Kicked {count} connections, revoked {revoked} sessions"}


@admin_router.post("/kick")
async def kick_ip(
    body: AdminKickRequest,
    _: str = Depends(require_admin),
):
    """踢出并封禁指定 IP 矿工"""
    target_ip = body.ip

    # 0. 将 IP 加入黑名单（持久封禁，直到手动解封或重启）
    state.ban_ip(target_ip)

    # 1. 吊销该 IP 的所有 Token（阻止前端重连时通过 validate 校验）
    revoked = state.revoke_tokens_by_ip(target_ip)

    # 2. 收集需要踢出的 WebSocket 连接
    to_kick = []
    for ws, data in list(state.client_hashrates.items()):
        if data.get("ip") == target_ip:
            to_kick.append(ws)

    # 也从 session_tokens 找（token 已 revoked 但 websocket 引用已被清空，
    # 此处作为兜底检查 active_connections）
    for ws in list(state.active_connections):
        # 通过 client_hashrates 中的 IP 信息匹配
        hr_data = state.client_hashrates.get(ws)
        if hr_data and hr_data.get("ip") == target_ip and ws not in to_kick:
            to_kick.append(ws)

    # 3. 关闭 WebSocket 连接
    kicked = 0
    for ws in to_kick:
        try:
            await ws.close(code=1000, reason="Kicked by admin")
            kicked += 1
        except Exception:
            pass

    logger.info(
        "Kicked IP %s (%d connections, %d sessions revoked, IP banned)",
        target_ip, kicked, revoked,
    )
    return {"message": f"Banned and kicked {kicked} connections, revoked {revoked} sessions for IP {target_ip}"}


@admin_router.post("/unban")
async def unban_ip(
    body: AdminUnbanRequest,
    _: str = Depends(require_admin),
):
    """解除指定 IP 的封禁"""
    removed = state.unban_ip(body.ip)
    if removed:
        logger.info("Unbanned IP %s", body.ip)
        return {"message": f"Unbanned IP {body.ip}"}
    return {"message": f"IP {body.ip} was not in blacklist"}


@admin_router.get("/blacklist")
async def get_blacklist(_: str = Depends(require_admin)):
    """返回当前黑名单"""
    return state.get_banned_ips()


@admin_router.post("/clear-sessions")
async def clear_sessions(_: str = Depends(require_admin)):
    """清空所有 Session Token 并断开关联的 WebSocket 连接"""
    # 1. 先收集仍有连接的 WebSocket
    to_close = []
    for token_str, data in state.session_tokens.items():
        ws = data.get("websocket")
        if ws and data.get("is_connected"):
            to_close.append(ws)

    # 2. 吊销所有 Token（阻止前端重连时通过 validate 校验）
    revoked = state.revoke_all_tokens()

    # 3. 再关闭 WebSocket 连接
    closed = 0
    for ws in to_close:
        try:
            await ws.close(code=1000, reason="Session cleared by admin")
            closed += 1
        except Exception:
            pass

    logger.info("Cleared %d session tokens, closed %d connections", revoked, closed)
    return {"message": f"Cleared {revoked} session tokens, closed {closed} connections"}


@admin_router.post("/regenerate-hmac")
async def regenerate_hmac(
    body: Optional[AdminHmacUpdate] = None,
    _: str = Depends(require_admin),
):
    """设置或随机生成 HMAC 密钥"""
    if body and body.hmac_secret:
        hex_str = body.hmac_secret.strip()
        try:
            key_bytes = bytes.fromhex(hex_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid hex string")
        if len(key_bytes) < 16:
            raise HTTPException(status_code=400, detail="HMAC secret must be at least 128-bit (32 hex chars)")
        state.hmac_secret = key_bytes
        logger.info("HMAC secret updated via admin panel (%d bytes)", len(key_bytes))
        return {"message": f"HMAC secret updated ({len(key_bytes) * 8}-bit). All old invite codes are now invalid."}
    else:
        import secrets
        state.hmac_secret = secrets.token_bytes(32)
        logger.info("HMAC secret regenerated randomly (old invite codes invalidated)")
        return {"message": "HMAC secret regenerated (256-bit random). All old invite codes are now invalid."}


# ===== Admin WebSocket =====


@admin_router.websocket("/ws")
async def admin_ws(websocket: WebSocket):
    """Admin 专属 WebSocket，实时推送系统状态"""
    # 从 query param 获取 token 认证
    token = websocket.query_params.get("token", "")
    import hmac as hmac_mod
    import os

    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token or not hmac_mod.compare_digest(token, admin_token):
        await websocket.close(code=1008, reason="Invalid admin token")
        return

    await websocket.accept()
    state.admin_connections.add(websocket)
    logger.info("Admin WebSocket connected (total: %d)", len(state.admin_connections))

    try:
        while True:
            # 每 2 秒推送状态
            snapshot = state.get_status_snapshot()
            network = await state.get_network_hashrate()
            snapshot["total_hashrate"] = round(network["total_hashrate"], 2)
            await websocket.send_json({"type": "STATUS_UPDATE", **snapshot})
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        state.admin_connections.discard(websocket)
        logger.info("Admin WebSocket disconnected (total: %d)", len(state.admin_connections))
