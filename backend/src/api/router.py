"""API router assembly — mounts all sub-routers under /api/v1."""

from fastapi import APIRouter

from src.api.leaderboard import router as leaderboard_router
from src.api.agents import router as agents_router
from src.api.challenges import router as challenges_router
from src.api.strategies import router as strategies_router
from src.api.admin import router as admin_router
from src.api.failure_taxonomy import router as failure_taxonomy_router
from src.api.instances_operator import router as instances_operator_router
from src.api.instances import router as instances_router
from src.api.templates import router as templates_router
from src.api.flagship import router as flagship_router
from src.api.cats import router as cats_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(leaderboard_router, tags=["leaderboard"])
api_router.include_router(agents_router, tags=["agents"])
api_router.include_router(challenges_router, tags=["challenges"])
api_router.include_router(strategies_router, tags=["strategies"])
api_router.include_router(admin_router, tags=["admin"])
api_router.include_router(failure_taxonomy_router, tags=["failure-taxonomy"])
# instances_operator_router (prefix="/instances/operator") MUST be
# registered before instances_router (prefix="/instances") so
# /instances/operator/* matches the operator routes before FastAPI
# tries to cast "operator" to the int {instance_id} path param.
api_router.include_router(instances_operator_router)
api_router.include_router(instances_router)
api_router.include_router(templates_router)
api_router.include_router(flagship_router)
api_router.include_router(cats_router, tags=["cats"])
