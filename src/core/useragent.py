import re
from typing import Optional, Tuple

# 已知自动化工具黑名单（编译一次，import 时执行）
_BOT_PATTERN = re.compile(
    r"(?i)"
    r"(?:curl|wget|python-requests|python-httpx|python-urllib|httpx|"
    r"Go-http-client|Java/|Apache-HttpClient|"
    r"PostmanRuntime|insomnia|HTTPie|"
    r"node-fetch|axios|undici|got/|superagent|"
    r"scrapy|mechanize|aiohttp|"
    r"bot|crawler|spider|headless)"
)


def validate_user_agent(ua: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    验证 User-Agent 是否来自真实浏览器

    Returns:
        (is_valid, error_message)
        - (True, None) 表示通过
        - (False, "reason") 表示拒绝
    """
    # 1. 拒绝空/缺失 UA
    if not ua or not ua.strip():
        return False, "Missing User-Agent header"

    # 2. 已知自动化工具黑名单
    if _BOT_PATTERN.search(ua):
        return False, "Automated client detected"

    # 3. 要求 UA 以 Mozilla/5.0 开头（所有主流浏览器的通用前缀）
    if not ua.startswith("Mozilla/5.0"):
        return False, "Invalid User-Agent format"

    return True, None
