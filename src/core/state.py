import asyncio
import json
import math
import os
import secrets
import time
from datetime import datetime
from typing import Any, Dict, Optional, Set

from argon2 import PasswordHasher, Type
from fastapi import WebSocket


class SystemState:
    """全局内存状态 - 维护原子锁和谜题"""

    def __init__(self):
        self.lock = asyncio.Lock()
        self.current_seed = secrets.token_hex(16)

        # 从环境变量读取难度配置（带默认值，单位：前导零比特数）
        self.difficulty = int(os.getenv("HASHPASS_DIFFICULTY", "12"))
        self.min_difficulty = int(os.getenv("HASHPASS_MIN_DIFFICULTY", "4"))
        self.max_difficulty = int(os.getenv("HASHPASS_MAX_DIFFICULTY", "24"))
        self.target_time_min = int(os.getenv("HASHPASS_TARGET_TIME_MIN", "30"))
        self.target_time_max = int(os.getenv("HASHPASS_TARGET_TIME_MAX", "120"))

        # 时间跟踪
        self.puzzle_start_time = time.time()  # 当前puzzle开始时间（绝对时间）
        self.last_solve_time: Optional[float] = None  # 上次解题耗时

        # 挖矿状态跟踪（只在有矿工挖矿时计时）
        self.active_miners: Set[WebSocket] = set()  # 正在挖矿的矿工连接
        self.total_mining_time: float = 0.0  # 累计挖矿时间（秒）
        self.last_mining_state_change: Optional[float] = None  # 上次挖矿状态改变时间
        self.is_mining_active: bool = False  # 当前是否有矿工在挖矿

        # HMAC 密钥 - 用于派生邀请码（私有，不对外暴露）
        # 服务器启动时生成，重启后会重新生成（增强安全性）
        self.hmac_secret = secrets.token_bytes(32)  # 256-bit 密钥

        # 从环境变量读取 Argon2 配置（保存为实例变量以供验证使用）
        self.argon2_time_cost = int(os.getenv("HASHPASS_ARGON2_TIME_COST", "3"))
        self.argon2_memory_cost = int(os.getenv("HASHPASS_ARGON2_MEMORY_COST", "65536"))
        self.argon2_parallelism = int(os.getenv("HASHPASS_ARGON2_PARALLELISM", "1"))

        # 前端并行 Worker 数量
        self.worker_count = int(os.getenv("HASHPASS_WORKER_COUNT", "1"))

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
        self.aggregation_task: Optional[asyncio.Task] = None
        self.hashrate_stale_timeout: float = 10.0  # 10秒无更新视为过时

        # 超时检查任务
        self.timeout_task: Optional[asyncio.Task] = None

        # Session Token 清理任务
        self.cleanup_task: Optional[asyncio.Task] = None

        # Admin WebSocket 连接集合
        self.admin_connections: Set[WebSocket] = set()

        # IP 黑名单（内存态，重启清空）
        self.banned_ips: Set[str] = set()

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
            print(f"[Mining Timer] ⏱️ 开始计时 - 首位矿工上线")

        self.active_miners.add(ws)
        print(f"[Active Miners] 矿工上线 | 当前在线: {len(self.active_miners)}")

    def stop_miner(self, ws: WebSocket) -> None:
        """记录矿工停止挖矿"""
        if ws not in self.active_miners:
            return  # 本来就没在挖矿

        self.active_miners.discard(ws)

        # 如果是最后一个矿工，暂停计时
        if len(self.active_miners) == 0 and self.is_mining_active:
            self._pause_mining_timer()
            print(f"[Mining Timer] ⏸️ 暂停计时 - 所有矿工离线")

        print(f"[Active Miners] 矿工下线 | 当前在线: {len(self.active_miners)}")

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

    def _calculate_difficulty_step(self, solve_time: float) -> int:
        """
        根据解题时间与目标中位时间的偏离比例，计算难度调整步数。

        使用 log2(target_midpoint / solve_time) 将时间偏离直接映射为 bit 数变化：
        - 解题时间是目标的 1/2 → +1 bit
        - 解题时间是目标的 1/4 → +2 bit
        - 解题时间是目标的 1/8 → +3 bit
        - 解题时间是目标的 2x  → -1 bit
        - 解题时间是目标的 4x  → -2 bit

        Returns:
            正数表示应增加难度，负数表示应降低难度，0 表示不调整
        """
        target_midpoint = (self.target_time_min + self.target_time_max) / 2

        if solve_time < self.target_time_min:
            # 解题太快 → 正向调整（增加难度）
            # solve_time 越小，ratio 越大，step 越大
            ratio = target_midpoint / max(solve_time, 0.1)  # 防止除零
            step = math.floor(math.log2(ratio))
            return max(1, min(step, 4))  # clamp 到 [1, 4]

        elif solve_time > self.target_time_max:
            # 解题太慢 → 负向调整（降低难度）
            ratio = solve_time / target_midpoint
            step = math.floor(math.log2(ratio))
            return -max(1, min(step, 4))  # clamp 到 [-4, -1]

        else:
            return 0  # 在目标区间内，不调整

    def adjust_difficulty(self, solve_time: float) -> tuple[int, int, str]:
        """
        根据解题时间调整难度（比例步进算法）

        偏离目标时间越大，调整步数越大（±1~4 bit），实现快速收敛。

        Args:
            solve_time: 解题耗时（秒）

        Returns:
            (old_difficulty, new_difficulty, reason)
        """
        old_difficulty = self.difficulty
        step = self._calculate_difficulty_step(solve_time)

        if step > 0:
            # 增加难度
            new_diff = min(self.difficulty + step, self.max_difficulty)
            actual_step = new_diff - self.difficulty
            if actual_step > 0:
                self.difficulty = new_diff
                reason = (
                    f"Solved too fast ({solve_time:.1f}s < {self.target_time_min}s), "
                    f"+{actual_step} bit(s)"
                )
            else:
                reason = f"Already at max difficulty ({self.max_difficulty})"
        elif step < 0:
            # 降低难度
            new_diff = max(self.difficulty + step, self.min_difficulty)
            actual_step = self.difficulty - new_diff
            if actual_step > 0:
                self.difficulty = new_diff
                reason = (
                    f"Solved too slow ({solve_time:.1f}s > {self.target_time_max}s), "
                    f"-{actual_step} bit(s)"
                )
            else:
                reason = f"Already at min difficulty ({self.min_difficulty})"
        else:
            reason = f"Perfect timing ({solve_time:.1f}s within {self.target_time_min}-{self.target_time_max}s)"

        self.last_solve_time = solve_time
        return old_difficulty, self.difficulty, reason

    async def start_timeout_checker(self):
        """启动超时检查任务"""
        if self.timeout_task and not self.timeout_task.done():
            self.timeout_task.cancel()

        self.timeout_task = asyncio.create_task(self._check_timeout())

    async def _check_timeout(self):
        """
        检查puzzle是否超时，超时则降低难度并重置
        只在有矿工挖矿时计时（挖矿时间累计达到target_time_max才超时）
        """
        try:
            check_interval = 5.0  # 每5秒检查一次

            while True:
                await asyncio.sleep(check_interval)

                # 获取当前累计挖矿时间
                mining_time = self.get_current_mining_time()

                # 检查是否超时（只看挖矿时间）
                if mining_time >= self.target_time_max:
                    # 进入锁检查是否仍然是同一个puzzle
                    async with self.lock:
                        # 二次确认超时（防止在等待锁期间puzzle已被解出）
                        mining_time = self.get_current_mining_time()

                        if mining_time >= self.target_time_max:
                            old_difficulty = self.difficulty

                            # 使用比例步进降低难度（超时场景最少降2 bit，更积极地收敛）
                            step = self._calculate_difficulty_step(mining_time)
                            # step 应该是负数（超时意味着太慢），但超时比普通慢更严重
                            timeout_step = min(step, -2)  # 至少降 2 bit
                            new_diff = max(self.difficulty + timeout_step, self.min_difficulty)
                            actual_step = self.difficulty - new_diff

                            if actual_step > 0:
                                self.difficulty = new_diff
                                reason = f"Timeout (mining time: {mining_time:.1f}s > {self.target_time_max}s) - auto reducing by {actual_step} bit(s)"
                            else:
                                reason = f"Timeout (mining time: {mining_time:.1f}s) but already at min difficulty"

                            print(
                                f"[Difficulty Adjustment] {reason}: {old_difficulty} -> {self.difficulty}"
                            )

                            # 重置puzzle
                            self.reset_puzzle()

                            # 广播重置通知
                            await self.broadcast_puzzle_reset()

                            # 重新启动超时检查
                            await self.start_timeout_checker()

                            # 退出当前检查循环
                            break

        except asyncio.CancelledError:
            # 任务被取消（正常情况：puzzle被解出）
            pass
        except Exception as e:
            print(f"[Timeout Checker Error] {e}")

    async def broadcast_puzzle_reset(self):
        """广播 puzzle 重置通知给所有连接的客户端（并行发送）"""
        message = json.dumps(
            {
                "type": "PUZZLE_RESET",
                "seed": self.current_seed,
                "difficulty": self.difficulty,
            }
        )

        # ===== 关键修复：先将 set 转为 list，避免并发修改导致 zip 不匹配 =====
        connections_snapshot = list(self.active_connections)

        # 并行发送消息到所有连接
        tasks = [connection.send_text(message) for connection in connections_snapshot]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 清理发送失败的连接
        disconnected = set()
        for connection, result in zip(connections_snapshot, results):
            if isinstance(result, Exception):
                disconnected.add(connection)
                print(
                    f"[Broadcast] Failed to send PUZZLE_RESET to connection: {result}"
                )

        self.active_connections -= disconnected

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

        # ===== 关键修复：先将 set 转为 list，避免并发修改导致 zip 不匹配 =====
        connections_snapshot = list(self.active_connections)

        # 并行发送消息到所有连接
        tasks = [connection.send_text(message) for connection in connections_snapshot]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 清理发送失败的连接
        disconnected = set()
        for connection, result in zip(connections_snapshot, results):
            if isinstance(result, Exception):
                disconnected.add(connection)
                # 不打印日志，避免刷屏（hashrate 每5秒广播一次）

        self.active_connections -= disconnected

    async def update_client_hashrate(
        self, ws: WebSocket, rate: float, client_ip: str
    ) -> None:
        """更新客户端算力数据"""
        self.client_hashrates[ws] = {
            "rate": rate,
            "timestamp": time.time(),
            "ip": client_ip,
        }

    async def remove_client_hashrate(self, ws: WebSocket) -> None:
        """客户端断开时移除算力数据"""
        self.client_hashrates.pop(ws, None)

    async def get_network_hashrate(self) -> Dict[str, float]:
        """计算全网算力（过滤过时数据）"""
        current_time = time.time()
        active_rates = []
        stale_connections = []

        for ws, data in self.client_hashrates.items():
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
                    stats = await self.get_network_hashrate()

                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(
                        f"[{timestamp}] [全网算力] 总计: {stats['total_hashrate']:.2f} H/s | "
                        f"活跃矿工: {stats['active_miners']} | "
                        f"已清理过时: {stats['stale_removed']}"
                    )

                    # 广播全网算力到所有连接的客户端
                    await self.broadcast_network_hashrate(stats)
                except asyncio.CancelledError:
                    print("[算力聚合] 任务已取消")
                    break
                except Exception as e:
                    print(f"[算力聚合] 错误: {e}")

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
        }
        print(
            f"[Session Token] ✓ 生成 Token for IP {ip} (连接数: {len(self.session_tokens)})"
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
            print(f"[Session Token] ✗ Token 已被吊销 (IP: {token_data['ip']})")
            return False

        # 验证 IP 一致性
        if token_data["ip"] != request_ip:
            print(
                f"[Session Token] ✗ IP 不匹配: Token IP={token_data['ip']}, Request IP={request_ip}"
            )
            return False

        # 检查是否已过期（未连接超过5分钟）
        if not token_data["is_connected"]:
            disconnected_at = token_data.get("disconnected_at")
            if disconnected_at is not None:
                time_since_disconnect = time.time() - disconnected_at
                if time_since_disconnect > self.token_expiry_seconds:
                    print(
                        f"[Session Token] ✗ Token 已过期 (断开 {time_since_disconnect:.1f}s > {self.token_expiry_seconds}s)"
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
        for token, data in self.session_tokens.items():
            if data["websocket"] == websocket:
                # 标记为未连接
                data["is_connected"] = False
                data["disconnected_at"] = time.time()
                data["websocket"] = None  # 清除 WebSocket 引用，避免内存泄漏
                print(
                    f"[Session Token] ⏱️ Token 标记为未连接 (将在5分钟后过期，剩余: {len(self.session_tokens)})"
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

        print(f"[Session Token] ✓ Token 重连成功 (IP: {token_data['ip']})")
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
        for token, data in self.session_tokens.items():
            if data.get("ip") == ip and not data.get("revoked"):
                data["revoked"] = True
                data["is_connected"] = False
                data["disconnected_at"] = time.time()
                data["websocket"] = None
                revoked += 1
        if revoked:
            print(f"[Session Token] 🚫 已吊销 IP {ip} 的 {revoked} 个 Token")
        return revoked

    def revoke_all_tokens(self) -> int:
        """
        吊销所有 Session Token（标记为已吊销）

        Token 不会立即删除，而是由清理任务统一回收。

        Returns:
            吊销的 Token 数量
        """
        revoked = 0
        for token, data in self.session_tokens.items():
            if not data.get("revoked"):
                data["revoked"] = True
                data["is_connected"] = False
                data["disconnected_at"] = time.time()
                data["websocket"] = None
                revoked += 1
        if revoked:
            print(f"[Session Token] 🚫 已吊销全部 {revoked} 个 Token")
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
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        print(
                            f"[{timestamp}] [Session Token Cleanup] "
                            f"已清理 {expired_count} 个过期 Token | "
                            f"剩余: {len(self.session_tokens)}"
                        )
                except asyncio.CancelledError:
                    print("[Session Token Cleanup] 任务已取消")
                    break
                except Exception as e:
                    print(f"[Session Token Cleanup] 错误: {e}")

        self.cleanup_task = asyncio.create_task(cleanup_loop())
        print("[Session Token Cleanup] ✓ 清理任务已启动")

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

        for token, data in self.session_tokens.items():
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
            "min_difficulty": self.min_difficulty,
            "max_difficulty": self.max_difficulty,
            "target_time_min": self.target_time_min,
            "target_time_max": self.target_time_max,
            "current_seed": self.current_seed,
            "puzzle_start_time": self.puzzle_start_time,
            "mining_time": round(self.get_current_mining_time(), 2),
            "is_mining_active": self.is_mining_active,
            "last_solve_time": self.last_solve_time,
            "active_miners": len(self.active_miners),
            "active_connections": len(self.active_connections),
            "session_count": len(self.session_tokens),
            "argon2_time_cost": self.argon2_time_cost,
            "argon2_memory_cost": self.argon2_memory_cost,
            "argon2_parallelism": self.argon2_parallelism,
            "worker_count": self.worker_count,
            "banned_ips_count": len(self.banned_ips),
        }

    def get_miners_info(self) -> list:
        """从 client_hashrates 提取矿工列表"""
        current_time = time.time()
        miners = []
        for ws, data in self.client_hashrates.items():
            miners.append({
                "ip": data.get("ip", "unknown"),
                "hashrate": round(data.get("rate", 0), 2),
                "last_seen": round(current_time - data.get("timestamp", current_time), 1),
            })
        return miners

    def get_sessions_info(self) -> list:
        """从 session_tokens 提取会话列表（去除 WebSocket 引用）"""
        sessions = []
        for token_str, data in self.session_tokens.items():
            sessions.append({
                "token_preview": token_str[:8] + "...",
                "ip": data.get("ip", "unknown"),
                "created_at": data.get("created_at"),
                "is_connected": data.get("is_connected", False),
                "disconnected_at": data.get("disconnected_at"),
            })
        return sessions

    def ban_ip(self, ip: str) -> bool:
        """将 IP 加入黑名单，返回是否为新增"""
        if ip in self.banned_ips:
            return False
        self.banned_ips.add(ip)
        print(f"[Blacklist] + Banned IP: {ip} (total: {len(self.banned_ips)})")
        return True

    def unban_ip(self, ip: str) -> bool:
        """将 IP 从黑名单移除，返回是否存在"""
        if ip not in self.banned_ips:
            return False
        self.banned_ips.discard(ip)
        print(f"[Blacklist] - Unbanned IP: {ip} (total: {len(self.banned_ips)})")
        return True

    def is_banned(self, ip: str) -> bool:
        """检查 IP 是否在黑名单中"""
        return ip in self.banned_ips

    def get_banned_ips(self) -> list[str]:
        """返回黑名单中所有 IP"""
        return sorted(self.banned_ips)

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
