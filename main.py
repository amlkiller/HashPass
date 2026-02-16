from src.core.event_loop import init_event_loop

init_event_loop()  # Must be called before any asyncio usage

# 加载环境变量
from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.routes import router
from src.core.executor import init_process_pool, shutdown_process_pool
from src.core.state import state
from src.core.turnstile import get_turnstile_config
from src.core.useragent import validate_user_agent


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """为所有响应添加安全相关的 HTTP 头"""

    CSP = "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://challenges.cloudflare.com https://cdn.jsdelivr.net https://esm.sh",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data:",
            "frame-src https://challenges.cloudflare.com",
            "connect-src 'self' https://cdn.jsdelivr.net https://esm.sh",
            "worker-src 'self' blob:",
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
            ua = request.headers.get("user-agent")
            is_valid, reason = validate_user_agent(ua)
            if not is_valid:
                print(f"[UA Block] {reason} | path={path} ua={ua!r}")
                return JSONResponse(
                    status_code=404,
                    content={"error"},
                )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动
    import asyncio

    loop = asyncio.get_running_loop()
    loop_type = type(loop).__name__
    print(f"[HashPass] Event loop: {loop_type}")

    # 初始化进程池
    init_process_pool()

    print("[HashPass] Starting timeout checker...")
    await state.start_timeout_checker()
    print("[HashPass] Starting hashrate aggregation...")
    await state.start_hashrate_aggregation()
    print("[HashPass] Starting session token cleanup...")
    await state.start_token_cleanup()
    print(f"[HashPass] Initial difficulty: {state.difficulty}")
    print(
        f"[HashPass] Target time range: {state.target_time_min}-{state.target_time_max}s"
    )

    # 验证 Turnstile 配置
    try:
        site_key, _, test_mode = get_turnstile_config()
        mode_text = "TEST MODE" if test_mode else "PRODUCTION"
        print(f"[Turnstile] Site Key: {site_key[:20]}... ({mode_text})")
    except RuntimeError as e:
        print(f"[Turnstile] Configuration error: {e}")
        raise

    yield

    # 关闭
    if state.timeout_task and not state.timeout_task.done():
        state.timeout_task.cancel()
        print("[HashPass] Timeout checker stopped")
    await state.stop_hashrate_aggregation()
    print("[HashPass] Hashrate aggregation stopped")
    await state.stop_token_cleanup()
    print("[HashPass] Session token cleanup stopped")

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

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    """返回前端页面"""
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import os

    import uvicorn

    # 从环境变量读取端口，默认 8000
    port = int(os.getenv("PORT", "8000"))

    # ⚠️ 必须单进程模式（workers=1）
    uvicorn.run(app, host="0.0.0.0", port=port, workers=1)
