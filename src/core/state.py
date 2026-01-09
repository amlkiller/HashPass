import asyncio
import json
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

        # 从环境变量读取难度配置（带默认值）
        self.difficulty = int(os.getenv("HASHPASS_DIFFICULTY", "3"))
        self.min_difficulty = int(os.getenv("HASHPASS_MIN_DIFFICULTY", "1"))
        self.max_difficulty = int(os.getenv("HASHPASS_MAX_DIFFICULTY", "6"))
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

        self.ph = PasswordHasher(
            time_cost=self.argon2_time_cost,
            memory_cost=self.argon2_memory_cost,
            parallelism=self.argon2_parallelism,
            hash_len=32,
            type=Type.ID,
        )

        # WebSocket 连接管理
        self.active_connections: Set[WebSocket] = set()

        # Session Token 管理（Token -> WebSocket + IP 映射）
        self.session_tokens: Dict[str, Dict[str, Any]] = {}
        # 结构: {
        #   "token_string": {
        #     "websocket": <WebSocket对象>,
        #     "ip": "203.0.113.45",
        #     "created_at": 1704712800.0
        #   }
        # }

        # 客户端算力跟踪
        self.client_hashrates: Dict[WebSocket, Dict[str, float]] = {}
        # 结构: {websocket: {"rate": 123.45, "timestamp": 1234567890.123, "ip": "1.2.3.4"}}
        self.aggregation_task: Optional[asyncio.Task] = None
        self.hashrate_stale_timeout: float = 10.0  # 10秒无更新视为过时

        # 超时检查任务
        self.timeout_task: Optional[asyncio.Task] = None

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

    def adjust_difficulty(self, solve_time: float) -> tuple[int, int, str]:
        """
        根据解题时间调整难度

        Args:
            solve_time: 解题耗时（秒）

        Returns:
            (old_difficulty, new_difficulty, reason)
        """
        old_difficulty = self.difficulty

        if solve_time < self.target_time_min:
            # 解题太快，增加难度
            if self.difficulty < self.max_difficulty:
                self.difficulty += 1
                reason = (
                    f"Solved too fast ({solve_time:.1f}s < {self.target_time_min}s)"
                )
            else:
                reason = f"Already at max difficulty ({self.max_difficulty})"
        elif solve_time > self.target_time_max:
            # 解题太慢，降低难度
            if self.difficulty > self.min_difficulty:
                self.difficulty -= 1
                reason = (
                    f"Solved too slow ({solve_time:.1f}s > {self.target_time_max}s)"
                )
            else:
                reason = f"Already at min difficulty ({self.min_difficulty})"
        else:
            # 在目标时间内，难度不变
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

                            # 降低难度
                            if self.difficulty > self.min_difficulty:
                                self.difficulty -= 1
                                reason = f"Timeout (mining time: {mining_time:.1f}s > {self.target_time_max}s) - auto reducing difficulty"
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

        # 并行发送消息到所有连接
        tasks = [
            connection.send_text(message) for connection in self.active_connections
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 清理发送失败的连接
        disconnected = set()
        for connection, result in zip(self.active_connections, results):
            if isinstance(result, Exception):
                disconnected.add(connection)

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

        # 并行发送消息到所有连接
        tasks = [
            connection.send_text(message) for connection in self.active_connections
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 清理发送失败的连接
        disconnected = set()
        for connection, result in zip(self.active_connections, results):
            if isinstance(result, Exception):
                disconnected.add(connection)

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
            "created_at": time.time()
        }
        print(f"[Session Token] ✓ 生成 Token for IP {ip} (连接数: {len(self.session_tokens)})")
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

        # 验证 IP 一致性
        if token_data["ip"] != request_ip:
            print(f"[Session Token] ✗ IP 不匹配: Token IP={token_data['ip']}, Request IP={request_ip}")
            return False

        return True

    def revoke_session_token(self, websocket: WebSocket) -> None:
        """
        撤销与 WebSocket 关联的所有 Session Token

        Args:
            websocket: 要撤销 Token 的 WebSocket 连接
        """
        # 找到该 WebSocket 对应的所有 Token
        tokens_to_remove = [
            token for token, data in self.session_tokens.items()
            if data["websocket"] == websocket
        ]

        # 删除找到的 Token
        for token in tokens_to_remove:
            del self.session_tokens[token]
            print(f"[Session Token] ✓ 已撤销 Token (剩余: {len(self.session_tokens)})")


# 全局单例
state = SystemState()
