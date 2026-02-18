import asyncio
import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def get_webhook_url() -> Optional[str]:
    """
    从环境变量获取 Webhook URL

    Returns:
        Webhook URL 或 None（如果未配置）
    """
    url = os.getenv("WEBHOOK_URL", "").strip()
    return url if url else None


def get_webhook_token() -> Optional[str]:
    """
    从环境变量获取 Webhook Bearer Token

    Returns:
        Bearer Token 或 None（如果未配置）
    """
    token = os.getenv("WEBHOOK_TOKEN", "").strip()
    return token if token else None


async def send_webhook_notification(visitor_id: str, invite_code: str) -> None:
    """
    异步发送 Webhook 通知（用户获胜时触发），失败后最多重试 3 次（指数退避）。

    Args:
        visitor_id: 设备指纹 ID
        invite_code: 生成的邀请码

    Note:
        此函数设计为非阻塞，即使全部重试失败也不会影响邀请码的发放
        支持 Bearer Token 鉴权（通过 WEBHOOK_TOKEN 环境变量配置）
    """
    webhook_url = get_webhook_url()

    # 如果未配置 Webhook URL，直接返回
    if not webhook_url:
        return

    payload = {"visitor_id": visitor_id, "invite_code": invite_code}

    # 构建请求头
    headers = {"Content-Type": "application/json"}

    # 如果配置了 Bearer Token，添加到请求头
    webhook_token = get_webhook_token()
    if webhook_token:
        headers["Authorization"] = f"Bearer {webhook_token}"

    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    webhook_url,
                    json=payload,
                    headers=headers,
                )

            if response.status_code == 200:
                logger.info("Webhook sent successfully -> %s", webhook_url)
                logger.debug("Webhook payload: %s", json.dumps(payload))
                return

            logger.warning(
                "Webhook server returned error status: %d (attempt %d/%d)",
                response.status_code, attempt + 1, max_attempts,
            )
            logger.warning("Webhook response: %s", response.text[:200])

        except httpx.TimeoutException:
            logger.error(
                "Webhook request timed out (5s) -> %s (attempt %d/%d)",
                webhook_url, attempt + 1, max_attempts,
            )
        except httpx.RequestError as e:
            logger.error(
                "Webhook network request failed: %s (attempt %d/%d)",
                e, attempt + 1, max_attempts,
            )
        except Exception as e:
            logger.error(
                "Webhook unknown error: %s (attempt %d/%d)",
                e, attempt + 1, max_attempts,
            )

        # Exponential backoff before next attempt (skip after last attempt)
        if attempt < max_attempts - 1:
            backoff = 2 ** attempt  # 1s, 2s
            logger.info("Webhook retrying in %ds...", backoff)
            await asyncio.sleep(backoff)

    logger.error("Webhook failed after %d attempts -> %s", max_attempts, webhook_url)
