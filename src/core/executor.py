"""
进程池管理器 - 用于 CPU 密集型任务的并行化

使用 ProcessPoolExecutor 绕过 Python GIL，避免 Argon2 验证阻塞事件循环
"""
import os
from concurrent.futures import ProcessPoolExecutor

# 全局进程池实例
_executor: ProcessPoolExecutor | None = None


def init_process_pool(max_workers: int | None = None) -> ProcessPoolExecutor:
    """
    初始化进程池

    Args:
        max_workers: 最大工作进程数，默认为 CPU 核心数

    Returns:
        ProcessPoolExecutor 实例
    """
    global _executor

    if _executor is not None:
        raise RuntimeError("Process pool already initialized")

    # 默认使用 CPU 核心数，但至少保留 1 个核心给主进程
    if max_workers is None:
        cpu_count = os.cpu_count() or 1
        max_workers = max(1, cpu_count - 1)

    _executor = ProcessPoolExecutor(max_workers=max_workers)
    print(f"[Executor] Process pool initialized with {max_workers} workers")

    return _executor


def get_process_pool() -> ProcessPoolExecutor:
    """
    获取全局进程池实例

    Returns:
        ProcessPoolExecutor 实例

    Raises:
        RuntimeError: 进程池未初始化
    """
    if _executor is None:
        raise RuntimeError("Process pool not initialized. Call init_process_pool() first.")

    return _executor


def shutdown_process_pool(wait: bool = True) -> None:
    """
    关闭进程池

    Args:
        wait: 是否等待所有任务完成
    """
    global _executor

    if _executor is not None:
        _executor.shutdown(wait=wait)
        print(f"[Executor] Process pool shutdown (wait={wait})")
        _executor = None
