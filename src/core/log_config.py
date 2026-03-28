"""Centralized logging configuration for HashPass"""

import logging
import logging.handlers
import os
import sys
from multiprocessing import current_process
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

    def __init__(self, *args, **kwargs):
        self._lock_stream = None
        self._lock_path = None
        super().__init__(*args, **kwargs)
        self._lock_path = f"{self.baseFilename}.lock"

    def emit(self, record):
        """
        重写 emit 方法，在写入日志前获取文件锁

        Args:
            record: LogRecord 对象
        """
        try:
            # 使用独立 lock 文件保护 rollover + write 的整个临界区。
            self._acquire_lock()
            try:
                if self.stream is None and (self.mode != "w" or not self._closed):
                    self.stream = self._open()
                logging.handlers.TimedRotatingFileHandler.emit(self, record)
                if self.stream:
                    self.flush()
            finally:
                self._release_lock()
        except Exception as e:
            # 记录错误到 stderr
            print(f"ERROR: Failed to emit log record: {e}", file=sys.stderr)
            self.handleError(record)

    def _ensure_lock_stream(self):
        """确保独立 lock 文件已打开。"""
        if self._lock_stream is None or self._lock_stream.closed:
            self._lock_stream = open(self._lock_path, "a+b")
        return self._lock_stream

    def _acquire_lock(self):
        """获取文件锁（阻塞式）"""
        try:
            lock_stream = self._ensure_lock_stream()
            if sys.platform == "win32":
                # msvcrt.locking 基于当前文件指针位置；固定到 offset 0，
                # 避免写日志后文件指针移动导致解锁目标错位。
                lock_stream.seek(0, os.SEEK_END)
                if lock_stream.tell() == 0:
                    lock_stream.write(b"\0")
                    lock_stream.flush()
                lock_stream.seek(0)
                msvcrt.locking(lock_stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        except (OSError, IOError) as e:
            # 文件锁获取失败时记录到 stderr（避免日志系统崩溃）
            print(f"WARNING: Failed to acquire file lock: {e}", file=sys.stderr)

    def _release_lock(self):
        """释放文件锁"""
        if self._lock_stream is None or self._lock_stream.closed:
            return

        try:
            if sys.platform == "win32":
                self._lock_stream.seek(0)
                msvcrt.locking(self._lock_stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._lock_stream.fileno(), fcntl.LOCK_UN)
        except (OSError, IOError) as e:
            # 文件锁释放失败时记录到 stderr
            print(f"WARNING: Failed to release file lock: {e}", file=sys.stderr)

    def close(self):
        try:
            if self._lock_stream is not None and not self._lock_stream.closed:
                self._lock_stream.close()
        finally:
            self._lock_stream = None
            super().close()


def setup_logging() -> None:
    """
    Configure the root logger for the application.

    - StreamHandler to sys.stdout (matches previous print() behavior)
    - TimedRotatingFileHandler to log/hashpass.log (daily rotation, 30 days retention)
    - Format: %(asctime)s [%(name)s] %(levelname)s %(message)s
    - Default level: INFO, configurable via HASHPASS_LOG_LEVEL env var
    """
    root = logging.getLogger()
    if getattr(root, "_hashpass_logging_configured", False):
        return

    level_name = os.getenv("HASHPASS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # Windows spawn 进程会再次导入 main.py。子进程不需要共享文件日志，
    # 否则会重复走日志初始化和文件锁路径。
    if current_process().name != "MainProcess":
        root.setLevel(level)
        root.addHandler(logging.NullHandler())
        root._hashpass_logging_configured = True
        return

    formatter = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    log_dir = Path("log")
    log_dir.mkdir(exist_ok=True)

    # 验证目录创建成功
    if not log_dir.exists():
        print(f"ERROR: Failed to create log directory: {log_dir.absolute()}", file=sys.stderr)
        # 仅使用 StreamHandler
        root.setLevel(level)
        root.addHandler(stream_handler)
        root._hashpass_logging_configured = True
        return

    try:
        file_handler = LockedTimedRotatingFileHandler(
            filename=log_dir / "hashpass.log",
            when="midnight",
            backupCount=30,
            encoding="utf-8",
            delay=False,
        )
        file_handler.setFormatter(formatter)
        file_handler.suffix = "%Y-%m-%d"

        # 验证文件处理器初始化成功
        if not file_handler.stream:
            print(f"WARNING: File handler stream not initialized", file=sys.stderr)

        root.setLevel(level)
        root.addHandler(stream_handler)
        root.addHandler(file_handler)
        root._hashpass_logging_configured = True

        # 写入测试日志验证文件处理器工作正常
        root.info("Logging system initialized successfully")

    except Exception as e:
        print(f"ERROR: Failed to initialize file handler: {e}", file=sys.stderr)
        # 降级到仅使用 StreamHandler
        root.setLevel(level)
        root.addHandler(stream_handler)
        root._hashpass_logging_configured = True
        root.warning("File logging disabled due to initialization error")
