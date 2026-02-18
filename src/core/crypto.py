import base64
import hashlib
import hmac

import argon2.low_level as alg


def verify_argon2_solution(
    nonce: int,
    seed: str,
    visitor_id: str,
    trace_data: str,
    submitted_hash: str,
    difficulty: int,
    time_cost: int,
    memory_cost: int,
    parallelism: int,
) -> tuple[bool, str | None]:
    """
    验证 Argon2 哈希解（进程安全版本）

    Args:
        nonce: 挖矿随机数
        seed: 谜题种子
        visitor_id: 设备指纹
        trace_data: Cloudflare Trace 数据
        submitted_hash: 客户端提交的哈希值
        difficulty: 难度（前导零比特数）
        time_cost: Argon2 时间成本参数
        memory_cost: Argon2 内存成本参数（KB）
        parallelism: Argon2 并行度参数

    Returns:
        (is_valid, error_message): 验证结果和错误消息（如果有）
    """

    # 重建 Salt（必须与前端一致）
    salt_raw = (seed + visitor_id + trace_data).encode("utf-8")

    # 重新计算哈希（使用与配置一致的参数）
    try:
        raw_hash = alg.hash_secret_raw(
            secret=str(nonce).encode("utf-8"),
            salt=salt_raw,
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=32,
            type=alg.Type.D,
        )
        hash_hex = raw_hash.hex()

        # 验证客户端提交的哈希是否正确（常量时间比较，防止时序攻击）
        if not hmac.compare_digest(hash_hex, submitted_hash):
            return (False, "Hash mismatch")

        # 验证难度（前 N 个比特为 0）
        hash_int = int(hash_hex, 16)
        leading_zero_bits = 256 - hash_int.bit_length() if hash_int else 256
        if leading_zero_bits < difficulty:
            return (
                False,
                f"Hash does not meet difficulty requirement ({difficulty} leading zero bits, found {leading_zero_bits})",
            )

        return (True, None)

    except Exception as e:
        return (False, f"Hash verification failed: {str(e)}")


def generate_invite_code(
    hmac_secret: bytes, visitor_id: str, nonce: int, seed: str
) -> str:
    """
    使用 HMAC-SHA256 派生邀请码

    Args:
        hmac_secret: 服务端私有密钥（256-bit）
        visitor_id: 设备指纹（ThumbmarkJS）
        nonce: 挖矿随机数
        seed: 谜题种子

    Returns:
        长度为 10 的邀请码字符串（URL-safe base64 编码）
    """
    # 构建输入数据：将所有唯一标识符组合
    # 这确保每个获胜者的邀请码都是唯一的且可验证的
    data = f"{visitor_id}:{nonce}:{seed}".encode("utf-8")

    # 使用 HMAC-SHA256 派生
    hmac_hash = hmac.new(hmac_secret, data, hashlib.sha256).digest()

    # 转换为 URL-safe base64 编码（移除填充）
    # base64 编码后取前 10 个字符作为邀请码
    invite_code = base64.urlsafe_b64encode(hmac_hash).decode("ascii").rstrip("=")[:10]

    return invite_code
