"""
Cloudflare Turnstile 验证模块
提供 token 验证和测试模式支持
"""

import logging
import os
from typing import Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# Turnstile Siteverify API 端点
SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# 测试密钥（总是通过）
TEST_SECRET_KEY = "1x0000000000000000000000000000000AA"
TEST_SITE_KEY = "1x00000000000000000000AA"

# 持久化 HTTP 客户端（懒惰初始化，复用连接）
_http_client: Optional[httpx.AsyncClient] = None


def get_turnstile_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=10.0)
    return _http_client


async def close_turnstile_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def get_turnstile_config() -> Tuple[str, str, bool]:
    """
    获取 Turnstile 配置

    Returns:
        (site_key, secret_key, test_mode)
    """
    test_mode = os.getenv("TURNSTILE_TEST_MODE", "false").lower() == "true"

    if test_mode:
        logger.info("Running in TEST MODE - all tokens will pass")
        return TEST_SITE_KEY, TEST_SECRET_KEY, True

    secret_key = os.getenv("TURNSTILE_SECRET_KEY")
    site_key = os.getenv("TURNSTILE_SITE_KEY")

    if not secret_key or not site_key:
        raise RuntimeError(
            "TURNSTILE_SECRET_KEY and TURNSTILE_SITE_KEY must be set in environment "
            "or enable TURNSTILE_TEST_MODE=true for development"
        )

    return site_key, secret_key, False


async def verify_turnstile_token(
    token: str, remote_ip: Optional[str] = None, secret_key: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """
    验证 Turnstile Token

    Args:
        token: 客户端提交的 cf-turnstile-response
        remote_ip: 客户端 IP（可选，建议提供）
        secret_key: Turnstile Secret Key（如果为 None，从环境变量读取）

    Returns:
        (is_valid, error_message)
    """
    if not token:
        return False, "Missing Turnstile token"

    # 获取密钥
    if secret_key is None:
        _, secret_key, _ = get_turnstile_config()

    # 构建请求参数
    payload = {
        "secret": secret_key,
        "response": token,
    }

    # 可选：绑定 IP 地址以增强安全性
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        # 调用 Cloudflare Siteverify API（复用持久连接）
        client = get_turnstile_client()
        response = await client.post(SITEVERIFY_URL, json=payload)
        response.raise_for_status()
        result = response.json()

        # 检查验证结果
        success = result.get("success", False)

        if not success:
            error_codes = result.get("error-codes", [])
            error_message = f"Turnstile verification failed: {', '.join(error_codes)}"
            logger.warning("Verification failed: %s", error_codes)
            return False, error_message

        # 验证成功
        logger.info("Token verified successfully for IP: %s", remote_ip)
        return True, None

    except httpx.HTTPError as e:
        error_message = f"Turnstile API error: {str(e)}"
        logger.error("HTTP error: %s", e)
        return False, error_message

    except Exception as e:
        error_message = f"Turnstile verification error: {str(e)}"
        logger.error("Unexpected error: %s", e)
        return False, error_message
