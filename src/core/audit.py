import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# 跨平台文件锁导入
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

logger = logging.getLogger(__name__)


def _acquire_file_lock(file_handle):
    """
    跨平台文件锁获取（阻塞式）

    Args:
        file_handle: 文件句柄（必须以写模式打开）
    """
    if sys.platform == "win32":
        # Windows: 锁定文件的第一个字节
        msvcrt.locking(file_handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        # Unix/Linux/macOS: 使用 fcntl 独占锁
        fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)


def _release_file_lock(file_handle):
    """
    跨平台文件锁释放

    Args:
        file_handle: 文件句柄
    """
    if sys.platform == "win32":
        # Windows: 解锁文件的第一个字节
        msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        # Unix/Linux/macOS: 释放 fcntl 锁
        fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


def _write_verify_log_sync(verify_file: Path, lock_file: Path, verify_data: dict) -> None:
    """
    同步写入验证日志（带文件锁）

    此函数在线程池中执行，避免阻塞 asyncio 事件循环
    """
    # 1. 获取文件锁
    with open(lock_file, "w") as lock_handle:
        _acquire_file_lock(lock_handle)

        try:
            # 2. 读取现有记录
            records = []
            if verify_file.exists():
                with open(verify_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content.strip():  # 防止空文件导致 JSON 解析错误
                        records = json.loads(content)

            # 3. 检查是否需要轮转（达到 1000 条）
            if len(records) >= 1000:
                # 创建归档文件
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                archive_file = verify_file.parent / f"verify_{timestamp}.json"

                # 将旧记录移动到归档文件
                with open(archive_file, "w", encoding="utf-8") as f:
                    f.write(json.dumps(records, ensure_ascii=False, indent=2))

                logger.info(
                    "Log rotation: archived %d records to %s",
                    len(records),
                    archive_file.name,
                )

                # 清空主文件记录
                records = []

            # 4. 追加新记录
            records.append(verify_data)

            # 5. 写入主文件（原子性写入：先写临时文件，再重命名）
            temp_file = verify_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(records, ensure_ascii=False, indent=2))

            # 原子性替换（Windows 需要先删除目标文件）
            if sys.platform == "win32" and verify_file.exists():
                verify_file.unlink()
            temp_file.replace(verify_file)

        finally:
            # 6. 释放文件锁
            _release_file_lock(lock_handle)


async def append_to_verify_log(verify_data: dict) -> None:
    """
    异步追加验证数据到 verify.json（带日志轮转和文件锁）
    此函数在锁外执行，避免阻塞其他验证请求

    日志轮转策略：
    - 每 1000 条记录创建新文件
    - 文件命名: verify_YYYYMMDD_HHMMSS.json
    - 主文件 verify.json 始终保持最新数据

    并发安全：
    - 使用文件锁防止多进程/多线程并发写入冲突
    - 支持跨平台（Windows: msvcrt, Unix: fcntl）
    """
    verify_file = Path("verify.json")
    lock_file = Path("verify.json.lock")

    loop = asyncio.get_running_loop()

    try:
        # 在线程池中执行文件锁操作（避免阻塞事件循环）
        await loop.run_in_executor(None, _write_verify_log_sync, verify_file, lock_file, verify_data)
    except Exception as e:
        logger.error("Failed to write verify.json: %s", e, exc_info=True)
