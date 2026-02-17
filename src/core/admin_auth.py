import hmac
import os

from fastapi import Header, HTTPException


def require_admin(authorization: str = Header(None)) -> str:
    """
    Admin Token 校验依赖函数

    验证 Authorization: Bearer <token> 是否匹配 ADMIN_TOKEN 环境变量。
    使用 hmac.compare_digest 常量时间比较，防止时序攻击。

    Returns:
        验证通过的 token 字符串

    Raises:
        HTTPException 401: ADMIN_TOKEN 未配置或缺少 Authorization header
        HTTPException 403: Token 不匹配
    """
    admin_token = os.getenv("ADMIN_TOKEN", "")

    if not admin_token:
        raise HTTPException(status_code=401, detail="ADMIN_TOKEN not configured")

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization format (expected 'Bearer <token>')",
        )

    token = authorization.removeprefix("Bearer ")

    if not hmac.compare_digest(token, admin_token):
        raise HTTPException(status_code=403, detail="Invalid admin token")

    return token
