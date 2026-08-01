# backend/routes/__init__.py
# 路由模块

from fastapi import FastAPI
from backend.routes.world import router as world_router
from backend.routes.ghost import router as ghost_router
from backend.routes.character import router as character_router
from backend.routes.location import router as location_router
from backend.routes.system import router as system_router
from backend.routes.settings import router as settings_router
from backend.routes.producer import router as producer_router
from backend.routes.records import router as records_router


def register_routes(app: FastAPI):
    """注册所有路由"""
    app.include_router(world_router, prefix="/api", tags=["world"])
    app.include_router(ghost_router, prefix="/api/ghost", tags=["ghost"])
    app.include_router(records_router, prefix="/api/ghost", tags=["records"])
    app.include_router(character_router, prefix="/api/ghost", tags=["character"])
    app.include_router(location_router, prefix="/api/ghost", tags=["location"])
    app.include_router(system_router, prefix="/api", tags=["system"])
    app.include_router(settings_router, prefix="/api/ghost", tags=["settings"])
    app.include_router(producer_router, prefix="/api/ghost", tags=["producer"])


__all__ = [
    'register_routes',
    'world_router',
    'ghost_router',
    'character_router',
    'location_router',
    'system_router',
    'settings_router',
    'producer_router',
    'records_router',
]
