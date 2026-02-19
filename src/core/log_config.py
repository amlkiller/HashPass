"""Centralized logging configuration for HashPass"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

# 跨平台文件锁导入
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class LockedTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """
    带文件锁的 TimedRotatingFileHandler

    在多进程/多线程环境下，使用文件锁确保日志写入的原子性，
    防止并发写入导致的日志损坏或丢失。

    支持跨平台：
    - Windows: msvcrt.locking
    - Unix/Linux/macOS: fcntl.flock
    """

    def emit(self, record):
        """
        重写 emit 方法，在写入日志前获取文件锁

        Args:
            record: LogRecord 对象
        """
        try:
            if self.shouldRollover(record):
                self.doRollover()

            if self.stream:
                # 获取文件锁
                self._acquire_lock()
                try:
                    # 调用父类的 emit 方法写入日志
                    logging.handlers.TimedRotatingFileHandler.emit(self, record)
                finally:
                    # 释放文件锁
                    self._release_lock()
        except Exception:
            self.handleError(record)

    def _acquire_lock(self):
        """获取文件锁（阻塞式）"""
        if self.stream and hasattr(self.stream, "fileno"):
            try:
                if sys.platform == "win32":
                    # Windows: 锁定文件的第一个字节
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    # Unix/Linux/macOS: 使用 fcntl 独占锁
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX)
            except (OSError, IOError):
                # 文件锁获取失败时静默处理（避免日志系统崩溃）
                pass

    def _release_lock(self):
        """释放文件锁"""
        if self.stream and hasattr(self.stream, "fileno"):
            try:
                if sys.platform == "win32":
                    # Windows: 解锁文件的第一个字节
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    # Unix/Linux/macOS: 释放 fcntl 锁
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            except (OSError, IOError):
                # 文件锁释放失败时静默处理
                pass


def setup_logging() -> None:
    """
    Configure the root logger for the application.

    - StreamHandler to sys.stdout (matches previous print() behavior)
    - TimedRotatingFileHandler to log/hashpass.log (daily rotation, 30 days retention)
    - Format: %(asctime)s [%(name)s] %(levelname)s %(message)s
    - Default level: INFO, configurable via HASHPASS_LOG_LEVEL env var
    """
    level_name = os.getenv("HASHPASS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    log_dir = Path("log")
    log_dir.mkdir(exist_ok=True)
    file_handler = LockedTimedRotatingFileHandler(
        filename=log_dir / "hashpass.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
        delay=False,
    )
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d"

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)
