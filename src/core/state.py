import asyncio
import json
import logging
import math
import os
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional, Set

import aiofiles
from argon2 import PasswordHasher, Type
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class SystemState:
    """全局内存状态 - 维护原子锁和谜题"""

    def __init__(self):
        self.lock = asyncio.Lock()
        self.current_seed = secrets.token_hex(16)

        # 从环境变量读取难度配置（带默认值，单位：前导零比特数）
        self.difficulty = int(os.getenv("HASHPASS_DIFFICULTY", "12"))
        self.min_difficulty = int(os.getenv("HASHPASS_MIN_DIFFICULTY", "4"))
        self.max_difficulty = int(os.getenv("HASHPASS_MAX_DIFFICULTY", "24"))
        self.difficulty_float: float = float(self.difficulty)
        self.target_time = int(os.getenv("HASHPASS_TARGET_TIME", "75"))
        self.target_timeout = int(os.getenv("HASHPASS_TARGET_TIMEOUT", "120"))

        # 时间跟踪
        self.puzzle_start_time = time.time()  # 当前puzzle开始时间（绝对时间）
        self.last_solve_time: Optional[float] = None  # 上次解题耗时
        self.solve_history: deque[float] = deque(maxlen=5)  # 最近5次解题耗时

        # EMA 平滑系数（N=5）
        self.ema_alpha: float = 2.0 / (5 + 1)
        self.ema_solve_time: Optional[float] = None

        # 挖矿状态跟踪（只在有矿工挖矿时计时）
        self.active_miners: Set[WebSocket] = set()  # 正在挖矿的矿工连接
        self.total_mining_time: float = 0.0  # 累计挖矿时间（秒）
        self.last_mining_state_change: Optional[float] = None  # 上次挖矿状态改变时间
        self.is_mining_active: bool = False  # 当前是否有矿工在挖矿

        # HMAC 密钥 - 用于派生邀请码（私有，不对外暴露）
        # 从环境变量读取（hex 编码），未设置时随机生成
        hmac_hex = os.getenv("HASHPASS_HMAC_SECRET", "")
        if hmac_hex:
            self.hmac_secret = bytes.fromhex(hmac_hex)
        else:
            self.hmac_secret = secrets.token_bytes(32)

        # 从环境变量读取 Argon2 配置（保存为实例变量以供验证使用）
        self.argon2_time_cost = int(os.getenv("HASHPASS_ARGON2_TIME_COST", "3"))
        self.argon2_memory_cost = int(os.getenv("HASHPASS_ARGON2_MEMORY_COST", "65536"))
        self.argon2_parallelism = int(os.getenv("HASHPASS_ARGON2_PARALLELISM", "1"))

        # 前端并行 Worker 数量
        self.worker_count = int(os.getenv("HASHPASS_WORKER_COUNT", "1"))

        # 最大允许计算速度（nonce/秒），0 表示禁用检查
        self.max_nonce_speed = float(os.getenv("HASHPASS_MAX_NONCE_SPEED", "0"))

        self.ph = PasswordHasher(
            time_cost=self.argon2_time_cost,
            memory_cost=self.argon2_memory_cost,
            parallelism=self.argon2_parallelism,
            hash_len=32,
            type=Type.D,
        )

        # WebSocket 连接管理
        self.active_connections: Set[WebSocket] = set()

        # Session Token 管理（Token -> WebSocket + IP 映射）
        self.session_tokens: Dict[str, Dict[str, Any]] = {}
        # 结构: {
        #   "token_string": {
        #     "websocket": <WebSocket对象或None>,
        #     "ip": "203.0.113.45",
        #     "created_at": 1704712800.0,
        #     "disconnected_at": None或时间戳,  # WebSocket断开时间
        #     "is_connected": True/False         # 当前是否连接
        #   }
        # }
        self.token_expiry_seconds = 300  # Token未连接过期时间：5分钟

        # 客户端算力跟踪
        self.client_hashrates: Dict[WebSocket, Dict[str, float]] = {}
        # 结构: {websocket: {"rate": 123.45, "timestamp": 1234567890.123, "ip": "1.2.3.4"}}

        # 超速矿工跟踪（上报算力超过 max_nonce_speed 的矿工）
        self.overspeed_hashrates: Dict[WebSocket, Dict[str, Any]] = {}
        # 结构同 client_hashrates，额外含 "reported_rate" 字段（实际上报值）
        self.aggregation_task: Optional[asyncio.Task] = None
        self.hashrate_stale_timeout: float = 10.0  # 10秒无更新视为过时

        # 超时检查任务
        self.timeout_task: Optional[asyncio.Task] = None

        # Session Token 清理任务
        self.cleanup_task: Optional[asyncio.Task] = None

        # Admin WebSocket 连接集合
        self.admin_connections: Set[WebSocket] = set()

        # IP 黑名单（持久化到 blacklist.json）
        self.banned_ips: Set[str] = set()

        # 管理面板图表历史（内存态，最多 50 点）
        self.chart_history_max: int = 50
        self.hashrate_chart_history: list = []  # 全网算力采样（每5秒一次）
        self.solve_time_chart_history: list = []  # 平均求解用时（每次解题时追加）

        # IP -> WebSocket 映射，追踪每个 IP 的活跃连接（限制同 IP 多开）
        self.ip_connections: Dict[str, WebSocket] = {}

        self._load_ema_from_history()

    def _load_ema_from_history(self, path: str = "verify.json") -> None:
        """从 verify.json 读取最近 N 条历史，计算初始 EMA。"""
        try:
            p = Path(path)
            if not p.exists():
                return
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, list) or not data:
                return
            N = round(2.0 / self.ema_alpha) - 1  # = 5
            times = [
                r["solve_time"]
                for r in data[-N:]
                if isinstance(r.get("solve_time"), (int, float)) and r["solve_time"] > 0
            ]
            if not times:
                return
            ema = times[0]
            for t in times[1:]:
                ema = self.ema_alpha * t + (1 - self.ema_alpha) * ema
            self.ema_solve_time = ema
            logger.info(
                "EMA solve time initialized: %.1fs (%d records)", ema, len(times)
            )
        except Exception as e:
            logger.warning("Failed to load EMA from history: %s", e)

    def reset_puzzle(self):
        """重置谜题（获胜后调用）"""
        self.current_seed = secrets.token_hex(16)
        self.puzzle_start_time = time.time()

        # 重置挖矿状态
        self.active_miners.clear()
        self.total_mining_time = 0.0
        self.last_mining_state_change = None
        self.is_mining_active = False

    def start_miner(self, ws: WebSocket) -> None:
        """记录矿工开始挖矿"""
        if ws in self.active_miners:
            return  # 已经在挖矿

        # 如果是第一个矿工，开始计时
        if len(self.active_miners) == 0:
            self.is_mining_active = True
            self.last_mining_state_change = time.time()
            logger.debug("Mining timer started - first miner online")

        self.active_miners.add(ws)
        logger.debug("Miner online | active miners: %d", len(self.active_miners))

    def stop_miner(self, ws: WebSocket) -> None:
        """记录矿工停止挖矿"""
        if ws not in self.active_miners:
            return  # 本来就没在挖矿

        self.active_miners.discard(ws)

        # 如果是最后一个矿工，暂停计时
        if len(self.active_miners) == 0 and self.is_mining_active:
            self._pause_mining_timer()
            logger.debug("Mining timer paused - all miners offline")

        logger.debug("Miner offline | active miners: %d", len(self.active_miners))

    def _pause_mining_timer(self) -> None:
        """暂停挖矿计时（内部方法）"""
        if self.is_mining_active and self.last_mining_state_change is not None:
            elapsed = time.time() - self.last_mining_state_change
            self.total_mining_time += elapsed
            self.is_mining_active = False
            self.last_mining_state_change = None

    def get_current_mining_time(self) -> float:
        """
        获取当前puzzle的累计挖矿时间（秒）
        只统计有矿工在线挖矿的时间
        """
        if self.is_mining_active and self.last_mining_state_change is not None:
            # 当前正在挖矿，加上当前段的时间
            current_segment = time.time() - self.last_mining_state_change
            return self.total_mining_time + current_segment
        else:
            # 当前暂停中，返回累计时间
            return self.total_mining_time

    def _calculate_smooth_adjustment(self, effective_time: float) -> float:
        """
        平滑比例控制：step = log2(target_time / effective_time)
        - 无死区、无 floor 离散化
        - 限幅到 [-4.0, +4.0]
        """
        ratio = self.target_time / max(effective_time, 0.1)
        step = math.log2(ratio)
        return max(-4.0, min(step, 4.0))

    def adjust_difficulty(self, solve_time: float) -> tuple[int, int, str]:
        """
        根据 EMA 解题时间调整难度（平滑比例控制 + 浮点累积）

        Args:
            solve_time: 解题耗时（秒）

        Returns:
            (old_difficulty, new_difficulty, reason)
        """
        old_difficulty = self.difficulty

        # 更新 EMA
        if self.ema_solve_time is None:
            self.ema_solve_time = solve_time
        else:
            self.ema_solve_time = (
                self.ema_alpha * solve_time + (1 - self.ema_alpha) * self.ema_solve_time
            )

        # 用 EMA 计算连续步长
        step = self._calculate_smooth_adjustment(self.ema_solve_time)

        # 累加到浮点难度并 clamp
        new_float = max(
            float(self.min_difficulty),
            min(self.difficulty_float + step, float(self.max_difficulty)),
        )
        self.difficulty_float = new_float
        new_difficulty = round(new_float)
        self.difficulty = new_difficulty

        change = new_difficulty - old_difficulty
        if change > 0:
            reason = (
                f"EMA={self.ema_solve_time:.1f}s raw={solve_time:.1f}s target={self.target_time}s, "
                f"+{change} bit(s) | step={step:+.3f} float={new_float:.3f}"
            )
        elif change < 0:
            reason = (
                f"EMA={self.ema_solve_time:.1f}s raw={solve_time:.1f}s target={self.target_time}s, "
                f"{change} bit(s) | step={step:+.3f} float={new_float:.3f}"
            )
        else:
            reason = (
                f"EMA={self.ema_solve_time:.1f}s raw={solve_time:.1f}s target={self.target_time}s, "
                f"no bit change | step={step:+.3f} float={new_float:.3f}"
            )

        self.last_solve_time = solve_time
        return old_difficulty, self.difficulty, reason

    def record_solve_time(self, solve_time: float) -> None:
        """记录解题耗时到滑动窗口历史（在原子锁内调用）"""
        self.solve_history.append(solve_time)
        self.solve_time_chart_history.append(solve_time)
        if len(self.solve_time_chart_history) > self.chart_history_max:
            self.solve_time_chart_history.pop(0)

    @property
    def average_solve_time(self) -> Optional[float]:
        if not self.solve_history:
            return None
        return round(sum(self.solve_history) / len(self.solve_history), 2)

    async def start_timeout_checker(self):
        """启动超时检查任务"""
        if self.timeout_task and not self.timeout_task.done():
            self.timeout_task.cancel()

        self.timeout_task = asyncio.create_task(self._check_timeout())

    async def _check_timeout(self):
        """
        检查puzzle是否超时，超时则降低难度并重置
        只在有矿工挖矿时计时（挖矿时间累计达到target_timeout才超时）
        """
        try:
            check_interval = 5.0  # 每5秒检查一次

            while True:
                await asyncio.sleep(check_interval)

                # 获取当前累计挖矿时间
                mining_time = self.get_current_mining_time()

                # 检查是否超时（只看挖矿时间）
                if mining_time >= self.target_timeout:
                    # 进入锁检查是否仍然是同一个puzzle
                    async with self.lock:
                        # 二次确认超时（防止在等待锁期间puzzle已被解出）
                        mining_time = self.get_current_mining_time()

                        if mining_time >= self.target_timeout:
                            # 将 target_timeout 作为虚拟解题时间注入 EMA
                            old_difficulty, new_difficulty, reason = self.adjust_difficulty(
                                self.target_timeout
                            )

                            logger.info(
                                "Difficulty adjustment (timeout %.1fs >= %ds): %s: %d -> %d",
                                mining_time,
                                self.target_timeout,
                                reason,
                                old_difficulty,
                                new_difficulty,
                            )

                            # 重置puzzle
                            self.reset_puzzle()

                            # 锁内快照消息（reset_puzzle 后状态已确定）
                            reset_msg = self.get_puzzle_reset_message()

                            # 重新启动超时检查
                            await self.start_timeout_checker()

                            # 退出当前检查循环（锁外广播在 break 后执行）
                            break

                    # 锁外：广播重置通知（O(N) I/O 不阻塞锁）
                    await self.broadcast_raw(reset_msg)
                    return

        except asyncio.CancelledError:
            # 任务被取消（正常情况：puzzle被解出）
            pass
        except Exception as e:
            logger.error("Timeout checker error: %s", e, exc_info=True)

    async def _broadcast(self, message: str) -> None:
        """并行广播消息给所有连接的客户端，清理断开的连接"""
        connections_snapshot = list(self.active_connections)
        tasks = [conn.send_text(message) for conn in connections_snapshot]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        disconnected = {
            conn
            for conn, result in zip(connections_snapshot, results)
            if isinstance(result, Exception)
        }
        self.active_connections -= disconnected
        if disconnected:
            logger.debug("Removed %d disconnected connections", len(disconnected))

    def get_puzzle_reset_message(self) -> str:
        """构建 puzzle 重置消息的 JSON 字符串（在锁内调用以捕获快照）"""
        return json.dumps(
            {
                "type": "PUZZLE_RESET",
                "seed": self.current_seed,
                "difficulty": self.difficulty,
                "solve_time": round(self.last_solve_time, 2)
                if self.last_solve_time is not None
                else None,
                "average_solve_time": self.average_solve_time,
                "puzzle_start_time": self.puzzle_start_time,
            }
        )

    async def broadcast_raw(self, message: str) -> None:
        """广播预构建的消息字符串给所有连接的客户端（在锁外调用）"""
        await self._broadcast(message)

    async def broadcast_puzzle_reset(self):
        """广播 puzzle 重置通知给所有连接的客户端（并行发送）"""
        await self._broadcast(self.get_puzzle_reset_message())

    async def broadcast_network_hashrate(self, stats: Dict[str, float]):
        """广播全网算力统计给所有连接的客户端（并行发送）"""
        message = json.dumps(
            {
                "type": "NETWORK_HASHRATE",
                "total_hashrate": round(stats["total_hashrate"], 2),
                "active_miners": stats["active_miners"],
                "timestamp": time.time(),
            }
        )
        await self._broadcast(message)

    async def update_client_hashrate(
        self, ws: WebSocket, rate: float, client_ip: str
    ) -> None:
        """更新客户端算力数据"""
        existing = self.client_hashrates.get(ws) or self.overspeed_hashrates.get(ws)
        connected_at = existing["connected_at"] if existing else time.time()
        self.client_hashrates[ws] = {
            "rate": rate,
            "timestamp": time.time(),
            "ip": client_ip,
            "connected_at": connected_at,
        }
        # 若曾被记为超速，清除（当前报告已合法）
        self.overspeed_hashrates.pop(ws, None)

    async def update_overspeed_hashrate(
        self, ws: WebSocket, rate: float, client_ip: str
    ) -> None:
        """记录上报算力超过速度限制的矿工"""
        existing = self.client_hashrates.get(ws) or self.overspeed_hashrates.get(ws)
        connected_at = existing["connected_at"] if existing else time.time()
        self.overspeed_hashrates[ws] = {
            "rate": rate,
            "timestamp": time.time(),
            "ip": client_ip,
            "connected_at": connected_at,
        }

    def remove_client_hashrate(self, ws: WebSocket) -> None:
        """客户端断开时移除算力数据"""
        self.client_hashrates.pop(ws, None)
        self.overspeed_hashrates.pop(ws, None)

    def get_network_hashrate(self) -> Dict[str, float]:
        """计算全网算力（过滤过时数据）"""
        current_time = time.time()
        active_rates = []
        stale_connections = []

        for ws, data in list(self.client_hashrates.items()):
            age = current_time - data["timestamp"]
            if age <= self.hashrate_stale_timeout:
                active_rates.append(data["rate"])
            else:
                stale_connections.append(ws)

        # 清理过时数据
        for ws in stale_connections:
            self.client_hashrates.pop(ws, None)

        return {
            "total_hashrate": sum(active_rates),
            "active_miners": len(active_rates),
            "stale_removed": len(stale_connections),
        }

    async def start_hashrate_aggregation(self) -> None:
        """启动算力聚合任务"""
        if self.aggregation_task is not None:
            return

        async def aggregation_loop():
            while True:
                try:
                    await asyncio.sleep(5.0)  # 每5秒
                    stats = self.get_network_hashrate()

                    # 追加算力历史（供管理面板图表使用）
                    self.hashrate_chart_history.append(
                        round(stats["total_hashrate"], 2)
                    )
                    if len(self.hashrate_chart_history) > self.chart_history_max:
                        self.hashrate_chart_history.pop(0)

                    logger.debug(
                        "Network hashrate: %.2f H/s | active miners: %d | stale removed: %d",
                        stats["total_hashrate"],
                        stats["active_miners"],
                        stats["stale_removed"],
                    )

                    # 广播全网算力到所有连接的客户端
                    await self.broadcast_network_hashrate(stats)
                except asyncio.CancelledError:
                    logger.debug("Hashrate aggregation task cancelled")
                    break
                except Exception as e:
                    logger.error("Hashrate aggregation error: %s", e, exc_info=True)

        self.aggregation_task = asyncio.create_task(aggregation_loop())

    async def stop_hashrate_aggregation(self) -> None:
        """停止算力聚合任务"""
        if self.aggregation_task is not None:
            self.aggregation_task.cancel()
            try:
                await self.aggregation_task
            except asyncio.CancelledError:
                pass
            self.aggregation_task = None

    def generate_session_token(self, websocket: WebSocket, ip: str) -> str:
        """
        为 WebSocket 连接生成 Session Token

        Args:
            websocket: WebSocket 连接对象
            ip: 客户端 IP 地址

        Returns:
            生成的 256 位随机 Token
        """
        token = secrets.token_urlsafe(32)  # 生成 256 位随机 Token
        self.session_tokens[token] = {
            "websocket": websocket,
            "ip": ip,
            "created_at": time.time(),
            "disconnected_at": None,
            "is_connected": True,
            "visitor_id": None,
        }
        logger.info(
            "Session token generated for IP %s (total sessions: %d)",
            ip,
            len(self.session_tokens),
        )
        return token

    def validate_session_token(self, token: str, request_ip: str) -> bool:
        """
        验证 Session Token 的有效性和 IP 一致性

        Args:
            token: 要验证的 Token
            request_ip: 请求来源的 IP 地址

        Returns:
            True 如果 Token 有效且 IP 匹配，否则 False
        """
        if token not in self.session_tokens:
            return False

        token_data = self.session_tokens[token]

        # 检查是否已被吊销
        if token_data.get("revoked"):
            logger.debug("Token revoked (IP: %s)", token_data["ip"])
            return False

        # 验证 IP 一致性
        if token_data["ip"] != request_ip:
            logger.debug(
                "Token IP mismatch: token_ip=%s, request_ip=%s",
                token_data["ip"],
                request_ip,
            )
            return False

        # 检查是否已过期（未连接超过5分钟）
        if not token_data["is_connected"]:
            disconnected_at = token_data.get("disconnected_at")
            if disconnected_at is not None:
                time_since_disconnect = time.time() - disconnected_at
                if time_since_disconnect > self.token_expiry_seconds:
                    logger.debug(
                        "Token expired (disconnected %.1fs > %ds)",
                        time_since_disconnect,
                        self.token_expiry_seconds,
                    )
                    return False

        return True

    def revoke_session_token(self, websocket: WebSocket) -> None:
        """
        标记与 WebSocket 关联的所有 Session Token 为未连接状态
        Token 不会立即删除，而是在5分钟未连接后由清理任务删除

        Args:
            websocket: 要标记 Token 的 WebSocket 连接
        """
        # 找到该 WebSocket 对应的所有 Token
        for token, data in list(self.session_tokens.items()):
            if data["websocket"] == websocket:
                # 标记为未连接
                data["is_connected"] = False
                data["disconnected_at"] = time.time()
                data["websocket"] = None  # 清除 WebSocket 引用，避免内存泄漏
                logger.debug(
                    "Token marked disconnected (will expire in 5min, remaining: %d)",
                    len(self.session_tokens),
                )

    def reconnect_session_token(self, token: str, websocket: WebSocket) -> bool:
        """
        重新激活已断开的 Session Token（用于 WebSocket 重连）

        Args:
            token: 要重新激活的 Token
            websocket: 新的 WebSocket 连接对象

        Returns:
            True 如果成功重连，False 如果 Token 不存在
        """
        if token not in self.session_tokens:
            return False

        token_data = self.session_tokens[token]
        token_data["websocket"] = websocket
        token_data["is_connected"] = True
        token_data["disconnected_at"] = None

        logger.info("Session token reconnected (IP: %s)", token_data["ip"])
        return True

    def revoke_tokens_by_ip(self, ip: str) -> int:
        """
        吊销指定 IP 的所有 Session Token（标记为已吊销）

        Token 不会立即删除，而是由清理任务统一回收。
        标记后 validate_session_token 会立即拒绝该 Token，
        阻止前端利用重连机制绕过吊销。

        Args:
            ip: 要吊销的 IP 地址

        Returns:
            吊销的 Token 数量
        """
        revoked = 0
        for token, data in list(self.session_tokens.items()):
            if data.get("ip") == ip and not data.get("revoked"):
                data["revoked"] = True
                data["is_connected"] = False
                data["disconnected_at"] = time.time()
                data["websocket"] = None
                revoked += 1
        if revoked:
            logger.info("Revoked %d token(s) for IP %s", revoked, ip)
        return revoked

    def revoke_all_tokens(self) -> int:
        """
        吊销所有 Session Token（标记为已吊销）

        Token 不会立即删除，而是由清理任务统一回收。

        Returns:
            吊销的 Token 数量
        """
        revoked = 0
        for token, data in list(self.session_tokens.items()):
            if not data.get("revoked"):
                data["revoked"] = True
                data["is_connected"] = False
                data["disconnected_at"] = time.time()
                data["websocket"] = None
                revoked += 1
        if revoked:
            logger.info("Revoked all %d token(s)", revoked)
        return revoked

    async def start_token_cleanup(self) -> None:
        """启动 Session Token 清理任务（每分钟检查一次）"""
        if self.cleanup_task is not None:
            return

        async def cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(60.0)  # 每60秒检查一次
                    expired_count = await self._cleanup_expired_tokens()
                    if expired_count > 0:
                        logger.debug(
                            "Cleaned up %d expired token(s) | remaining: %d",
                            expired_count,
                            len(self.session_tokens),
                        )
                except asyncio.CancelledError:
                    logger.debug("Session token cleanup task cancelled")
                    break
                except Exception as e:
                    logger.error("Session token cleanup error: %s", e, exc_info=True)

        self.cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info("Session token cleanup task started")

    async def stop_token_cleanup(self) -> None:
        """停止 Session Token 清理任务"""
        if self.cleanup_task is not None:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
            self.cleanup_task = None

    async def _cleanup_expired_tokens(self) -> int:
        """
        清理已吊销或未连接超过5分钟的 Session Token

        Returns:
            清理的 Token 数量
        """
        current_time = time.time()
        tokens_to_remove = []

        for token, data in list(self.session_tokens.items()):
            # 清理已吊销的 Token
            if data.get("revoked"):
                tokens_to_remove.append(token)
                continue

            # 清理未连接且超时的 Token
            if not data["is_connected"]:
                disconnected_at = data.get("disconnected_at")
                if disconnected_at is not None:
                    time_since_disconnect = current_time - disconnected_at
                    # 超过5分钟未连接，标记为待删除
                    if time_since_disconnect > self.token_expiry_seconds:
                        tokens_to_remove.append(token)

        # 批量删除过期 Token
        for token in tokens_to_remove:
            del self.session_tokens[token]

        return len(tokens_to_remove)

    def get_status_snapshot(self) -> dict:
        """返回可序列化的全量系统状态快照"""
        return {
            "difficulty": self.difficulty,
            "difficulty_float": round(self.difficulty_float, 3),
            "min_difficulty": self.min_difficulty,
            "max_difficulty": self.max_difficulty,
            "target_time": self.target_time,
            "target_timeout": self.target_timeout,
            "ema_solve_time": round(self.ema_solve_time, 2)
            if self.ema_solve_time is not None
            else None,
            "current_seed": self.current_seed,
            "puzzle_start_time": self.puzzle_start_time,
            "mining_time": round(self.get_current_mining_time(), 2),
            "is_mining_active": self.is_mining_active,
            "last_solve_time": self.last_solve_time,
            "solve_history": list(self.solve_history),
            "average_solve_time": self.average_solve_time,
            "active_miners": len(self.active_miners),
            "active_connections": len(self.active_connections),
            "session_count": len(self.session_tokens),
            "argon2_time_cost": self.argon2_time_cost,
            "argon2_memory_cost": self.argon2_memory_cost,
            "argon2_parallelism": self.argon2_parallelism,
            "worker_count": self.worker_count,
            "max_nonce_speed": self.max_nonce_speed,
            "banned_ips_count": len(self.banned_ips),
            "hashrate_chart_history": list(self.hashrate_chart_history),
            "solve_time_chart_history": list(self.solve_time_chart_history),
        }

    def get_miners_info(self) -> list:
        """从 client_hashrates 提取矿工列表（含超速矿工）"""
        current_time = time.time()
        miners = []
        seen_ws = set()

        for ws, data in list(self.client_hashrates.items()):
            age = current_time - data.get("timestamp", current_time)
            if age > self.hashrate_stale_timeout:
                continue
            seen_ws.add(ws)
            miners.append(
                {
                    "ip": data.get("ip", "unknown"),
                    "hashrate": round(data.get("rate", 0), 2),
                    "last_seen": round(age, 1),
                    "connected_since": round(
                        current_time - data.get("connected_at", current_time)
                    ),
                    "overspeed": False,
                }
            )

        for ws, data in self.overspeed_hashrates.items():
            if ws in seen_ws:
                continue  # 已在正常列表（不应发生，防御性检查）
            age = current_time - data.get("timestamp", current_time)
            if age > self.hashrate_stale_timeout:
                continue
            miners.append(
                {
                    "ip": data.get("ip", "unknown"),
                    "hashrate": round(data.get("rate", 0), 2),
                    "last_seen": round(age, 1),
                    "connected_since": round(
                        current_time - data.get("connected_at", current_time)
                    ),
                    "overspeed": True,
                }
            )

        return miners

    def get_sessions_info(self) -> list:
        """从 session_tokens 提取会话列表（去除 WebSocket 引用）"""
        sessions = []
        for token_str, data in list(self.session_tokens.items()):
            sessions.append(
                {
                    "token_preview": token_str[:8] + "...",
                    "ip": data.get("ip", "unknown"),
                    "created_at": data.get("created_at"),
                    "is_connected": data.get("is_connected", False),
                    "disconnected_at": data.get("disconnected_at"),
                }
            )
        return sessions

    def ban_ip(self, ip: str) -> bool:
        """将 IP 加入黑名单，返回是否为新增"""
        if ip in self.banned_ips:
            return False
        self.banned_ips.add(ip)
        logger.info("Banned IP: %s (total: %d)", ip, len(self.banned_ips))
        return True

    def unban_ip(self, ip: str) -> bool:
        """将 IP 从黑名单移除，返回是否存在"""
        if ip not in self.banned_ips:
            return False
        self.banned_ips.discard(ip)
        logger.info("Unbanned IP: %s (total: %d)", ip, len(self.banned_ips))
        return True

    def is_banned(self, ip: str) -> bool:
        """检查 IP 是否在黑名单中"""
        return ip in self.banned_ips

    def get_banned_ips(self) -> list[str]:
        """返回黑名单中所有 IP"""
        return sorted(self.banned_ips)

    def load_blacklist(self, path: str = "blacklist.json") -> None:
        """从文件加载黑名单（启动时调用）"""
        p = Path(path)
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self.banned_ips = set(data)
                logger.info("Loaded %d banned IPs from %s", len(self.banned_ips), path)
        except Exception as e:
            logger.error("Failed to load blacklist from %s: %s", path, e)

    async def save_blacklist(self, path: str = "blacklist.json") -> None:
        """异步将黑名单持久化到文件"""
        try:
            content = json.dumps(sorted(self.banned_ips), indent=2, ensure_ascii=False)
            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                await f.write(content)
        except Exception as e:
            logger.error("Failed to save blacklist to %s: %s", path, e)

    def has_active_connection(self, ip: str) -> bool:
        """检查该 IP 是否已有活跃 WebSocket 连接"""
        return ip in self.ip_connections

    def register_ip_connection(self, ip: str, ws: WebSocket) -> None:
        """注册 IP 与 WebSocket 的映射"""
        self.ip_connections[ip] = ws

    def unregister_ip_connection(self, ip: str, ws: WebSocket) -> None:
        """取消注册（仅当当前映射的 ws 匹配时才移除，防止误删）"""
        if self.ip_connections.get(ip) is ws:
            del self.ip_connections[ip]

    def get_ip_connection(self, ip: str) -> Optional[WebSocket]:
        """获取该 IP 当前的活跃 WebSocket"""
        return self.ip_connections.get(ip)

    async def broadcast_to_admins(self, message: dict):
        """广播消息给所有 Admin WebSocket 连接"""
        if not self.admin_connections:
            return

        text = json.dumps(message)
        connections_snapshot = list(self.admin_connections)
        tasks = [conn.send_text(text) for conn in connections_snapshot]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        disconnected = set()
        for conn, result in zip(connections_snapshot, results):
            if isinstance(result, Exception):
                disconnected.add(conn)

        self.admin_connections -= disconnected


# 全局单例
state = SystemState()
