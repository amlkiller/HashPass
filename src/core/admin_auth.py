import hmac
import os
import time

from fastapi import Header, HTTPException, Request

# Module-level state for brute-force protection
_failed_attempts: dict[str, int] = {}
_lockout_until: dict[str, float] = {}

_MAX_FAILURES = 10
_LOCKOUT_SECONDS = 300  # 5 minutes


def _get_client_ip(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or request.client.host


def require_admin(request: Request, authorization: str = Header(None)) -> str:
    """
    Admin Token 校验依赖函数

    验证 Authorization: Bearer <token> 是否匹配 ADMIN_TOKEN 环境变量。
    使用 hmac.compare_digest 常量时间比较，防止时序攻击。
    连续 10 次失败后锁定 IP 5 分钟。

    Returns:
        验证通过的 token 字符串

    Raises:
        HTTPException 401: ADMIN_TOKEN 未配置或缺少 Authorization header
        HTTPException 403: Token 不匹配
        HTTPException 429: IP 已被临时锁定
    """
    admin_token = os.getenv("ADMIN_TOKEN", "")

    if not admin_token:
        raise HTTPException(status_code=401, detail="ADMIN_TOKEN not configured")

    client_ip = _get_client_ip(request)

    # Check lockout
    lockout_ts = _lockout_until.get(client_ip, 0)
    if lockout_ts and time.time() < lockout_ts:
        remaining = int(lockout_ts - time.time())
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {remaining}s.",
        )

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization format (expected 'Bearer <token>')",
        )

    token = authorization.removeprefix("Bearer ")

    if not hmac.compare_digest(token, admin_token):
        attempts = _failed_attempts.get(client_ip, 0) + 1
        _failed_attempts[client_ip] = attempts
        if attempts >= _MAX_FAILURES:
            _lockout_until[client_ip] = time.time() + _LOCKOUT_SECONDS
            _failed_attempts[client_ip] = 0
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Locked out for {_LOCKOUT_SECONDS}s.",
            )
        raise HTTPException(status_code=403, detail="Invalid admin token")

    # Success — clear failure counter
    _failed_attempts.pop(client_ip, None)
    _lockout_until.pop(client_ip, None)
    return token
