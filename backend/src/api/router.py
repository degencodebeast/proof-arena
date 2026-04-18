"""API router assembly — mounts all sub-routers under /api/v1."""

from fastapi import APIRouter

from src.api.leaderboard import router as leaderboard_router
from src.api.agents import router as agents_router
from src.api.challenges import router as challenges_router
from src.api.strategies import router as strategies_router
from src.api.admin import router as admin_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(leaderboard_router, tags=["leaderboard"])
api_router.include_router(agents_router, tags=["agents"])
api_router.include_router(challenges_router, tags=["challenges"])
api_router.include_router(strategies_router, tags=["strategies"])
api_router.include_router(admin_router, tags=["admin"])
