from src.core.log_config import setup_logging

setup_logging()

from src.core.event_loop import init_event_loop

init_event_loop()  # Must be called before any asyncio usage

# 加载环境变量
import logging

from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.routes import router
from src.api.admin import admin_router
from src.core.executor import init_process_pool, shutdown_process_pool
from src.core.state import state
from src.core.turnstile import get_turnstile_config
from src.core.useragent import validate_user_agent

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """为所有响应添加安全相关的 HTTP 头"""

    CSP = "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.tailwindcss.com https://challenges.cloudflare.com https://cdn.jsdelivr.net https://esm.sh https://static.cloudflareinsights.com",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com https://cdn.tailwindcss.com data:",
            "img-src 'self' data:",
            "frame-src https://challenges.cloudflare.com",
            "connect-src 'self' https://cdn.jsdelivr.net https://esm.sh",
            "worker-src 'self' blob: https://esm.sh",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = self.CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        return response


class UserAgentMiddleware(BaseHTTPMiddleware):
    """拦截非浏览器客户端的 /api/ 请求"""

    EXEMPT_PATHS = {"/api/health", "/api/dev/trace"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in self.EXEMPT_PATHS:
            # 豁免 Admin API（允许 curl 访问）
            if path.startswith("/api/admin/"):
                return await call_next(request)
            ua = request.headers.get("user-agent")
            is_valid, reason = validate_user_agent(ua)
            if not is_valid:
                logger.warning("UA blocked: %s | path=%s ua=%r", reason, path, ua)
                return JSONResponse(
                    status_code=404,
                    content={"error": "Not found"},
                )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动
    import asyncio

    loop = asyncio.get_running_loop()
    loop_type = type(loop).__name__
    logger.info("Event loop: %s", loop_type)

    # 初始化进程池
    init_process_pool()

    logger.info("Starting timeout checker...")
    await state.start_timeout_checker()
    logger.info("Starting hashrate aggregation...")
    await state.start_hashrate_aggregation()
    logger.info("Starting session token cleanup...")
    await state.start_token_cleanup()
    logger.info("Initial difficulty: %d", state.difficulty)
    logger.info(
        "Target time range: %d-%ds", state.target_time_min, state.target_time_max
    )

    # 验证 Turnstile 配置
    try:
        site_key, _, test_mode = get_turnstile_config()
        mode_text = "TEST MODE" if test_mode else "PRODUCTION"
        logger.info("Turnstile Site Key: %s... (%s)", site_key[:20], mode_text)
    except RuntimeError as e:
        logger.error("Turnstile configuration error: %s", e)
        raise

    yield

    # 关闭
    if state.timeout_task and not state.timeout_task.done():
        state.timeout_task.cancel()
        logger.info("Timeout checker stopped")
    await state.stop_hashrate_aggregation()
    logger.info("Hashrate aggregation stopped")
    await state.stop_token_cleanup()
    logger.info("Session token cleanup stopped")

    # 关闭进程池
    shutdown_process_pool(wait=True)


app = FastAPI(
    title="HashPass",
    description="Atomic Hash-Lock Protocol Invite System",
    version="1.0.0",
    lifespan=lifespan,
)

# 中间件（Starlette 后注册 = 外层）
# UserAgentMiddleware 先注册（内层）：拦截非浏览器 /api/ 请求
# SecurityHeadersMiddleware 后注册（外层）：所有响应（含 403）都加安全头
app.add_middleware(UserAgentMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# 挂载 API 路由
app.include_router(router)
app.include_router(admin_router)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    """返回前端页面"""
    return FileResponse("static/index.html")


@app.get("/admin")
async def admin_page():
    """返回 Admin 控制面板页面"""
    return FileResponse("static/admin.html")


if __name__ == "__main__":
    import os

    import uvicorn

    # 从环境变量读取端口，默认 8000
    port = int(os.getenv("PORT", "8000"))

    # ⚠️ 必须单进程模式（workers=1）
    uvicorn.run(app, host="0.0.0.0", port=port, workers=1)
