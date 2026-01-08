import os
import asyncio
import json
from typing import Optional
import httpx


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
    异步发送 Webhook 通知（用户获胜时触发）

    Args:
        visitor_id: 设备指纹 ID
        invite_code: 生成的邀请码

    Note:
        此函数设计为非阻塞，即使失败也不会影响邀请码的发放
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

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers=headers,
            )

            if response.status_code == 200:
                print(f"[Webhook] ✓ 发送成功 -> {webhook_url}")
                print(f"[Webhook] Payload: {json.dumps(payload)}")
            else:
                print(
                    f"[Webhook] ✗ 服务器返回错误状态码: {response.status_code}"
                )
                print(f"[Webhook] Response: {response.text[:200]}")

    except httpx.TimeoutException:
        print(f"[Webhook] ✗ 请求超时 (5s) -> {webhook_url}")
    except httpx.RequestError as e:
        print(f"[Webhook] ✗ 网络请求失败: {e}")
    except Exception as e:
        print(f"[Webhook] ✗ 未知错误: {e}")
