# backend/routes/system.py
# 系统相关路由（健康检查、静态文件等）

from datetime import datetime
import json
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.config import BASE_DIR
from backend.version import APP_VERSION, DISPLAY_VERSION, VERSION_MANIFEST

router = APIRouter()

# ========== 静态文件挂载 ==========
js_dir = BASE_DIR / "js"
css_dir = BASE_DIR / "css"
avatars_dir = BASE_DIR / "avatars"

# 注意：静态文件挂载需要在主应用中执行，这里只定义路由


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": APP_VERSION, "timestamp": datetime.now().isoformat()}


@router.get("/version")
async def version_info():
    build = {}
    if getattr(sys, "frozen", False):
        try:
            build = json.loads((BASE_DIR / "build-info.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {
        "build_id": build.get("build_id"),
        "build_mode": "packaged" if getattr(sys, "frozen", False) else "source",
        "version": APP_VERSION,
        "display_version": DISPLAY_VERSION,
        "save_schema": VERSION_MANIFEST.get("save_schema", 8),
        "content_schema": VERSION_MANIFEST.get("content_schema", 8),
    }


@router.post("/shutdown")
async def shutdown_app(request: Request):
    from backend.services.turn_workflow import close_workflow_runtime

    await close_workflow_runtime()
    callback = getattr(request.app.state, "shutdown_callback", None)
    if not callback:
        return {"status": "ignored", "message": "当前为开发服务器"}
    callback()
    return {"status": "ok"}


@router.get("/")
async def serve_index():
    """服务首页"""
    index_path = BASE_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "TouHou API is running"}


def mount_static_files(app):
    """挂载静态文件目录（在主应用中调用）"""
    if js_dir.exists():
        app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")
        print(f"✅ 挂载 /js -> {js_dir}")
    if css_dir.exists():
        app.mount("/css", StaticFiles(directory=str(css_dir)), name="css")
        print(f"✅ 挂载 /css -> {css_dir}")
    if avatars_dir.exists():
        async def legacy_patchouli_avatar():
            return RedirectResponse("/avatars/npc_patchouli.png", status_code=307)

        app.add_api_route("/avatars/npc_patchouli_n.png", legacy_patchouli_avatar, methods=["GET", "HEAD"], include_in_schema=False)
        app.mount("/avatars", StaticFiles(directory=str(avatars_dir)), name="avatars")
        print(f"✅ 挂载 /avatars -> {avatars_dir}")
    static_dir = BASE_DIR / "static"
    if static_dir.exists():
        # Cached clients used /static/static; neither mount may expose BASE_DIR.
        app.mount("/static/static", StaticFiles(directory=str(static_dir)), name="static_legacy")
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
