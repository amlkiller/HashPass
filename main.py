from src.core.event_loop import init_event_loop
init_event_loop()  # Must be called before any asyncio usage

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.api.routes import router
from src.core.state import state
from src.core.turnstile import get_turnstile_config
from src.core.executor import init_process_pool, shutdown_process_pool
from contextlib import asynccontextmanager

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
    print(f"[HashPass] Initial difficulty: {state.difficulty}")
    print(f"[HashPass] Target time range: {state.target_time_min}-{state.target_time_max}s")

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

    # 关闭进程池
    shutdown_process_pool(wait=True)

app = FastAPI(
    title="HashPass",
    description="Atomic Hash-Lock Protocol Invite System",
    version="1.0.0",
    lifespan=lifespan
)

# 挂载 API 路由
app.include_router(router)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    """返回前端页面"""
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    import os

    # 从环境变量读取端口，默认 8000
    port = int(os.getenv("PORT", "8000"))

    # ⚠️ 必须单进程模式（workers=1）
    uvicorn.run(app, host="0.0.0.0", port=port, workers=1)
