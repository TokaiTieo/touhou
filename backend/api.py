# backend/api.py
# 主入口文件 - 只负责创建应用和注册路由

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import logging

from backend.config import APP_HOST, APP_PORT, APP_DEBUG, BASE_DIR, DATA_DIR, DEBUG
from backend.routes import register_routes
from backend.routes.system import mount_static_files
from backend.security import inject_session_token, require_local_session_token
from backend.utils.logging_config import configure_logging
from backend.version import APP_VERSION

configure_logging(DATA_DIR, DEBUG)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    try:
        yield
    finally:
        from backend.services.turn_workflow import close_workflow_runtime

        await close_workflow_runtime()


# 创建 FastAPI 应用
app = FastAPI(
    title="东方异变录 API",
    version=APP_VERSION,
    lifespan=app_lifespan,
)
app.middleware("http")(require_local_session_token)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器，确保所有错误返回JSON"""
    logger.exception("Unhandled API error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "description": f"服务器内部错误: {str(exc)[:100]}",
            "task_generated": False,
            "task": None,
            "task_data": None,
            "error": str(exc)
        }
    )

# 注册所有路由
register_routes(app)

# 挂载静态文件
mount_static_files(app)


@app.get("/")
async def serve_index():
    """服务首页"""
    index_path = BASE_DIR / "index.html"
    if index_path.exists():
        html = index_path.read_text(encoding="utf-8-sig")
        return HTMLResponse(inject_session_token(html))
    return {"message": "touhou API is running"}


# ========== 启动配置 ==========
if __name__ == "__main__":
    from backend.config import IS_FROZEN
    if IS_FROZEN:
        from backend.desktop_launcher import run_desktop
        try:
            run_desktop(app, APP_HOST, APP_PORT, DATA_DIR)
        except BaseException:
            logger.exception("Desktop startup failed")
            raise
    else:
        import uvicorn
        logger.info("TouHou API starting on http://%s:%s", APP_HOST, APP_PORT)
        uvicorn.run(app, host=APP_HOST, port=APP_PORT)
