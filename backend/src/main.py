"""Agent Arena backend — FastAPI application bootstrap."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # Startup: nothing blocking for now — DB pool is lazy, Solana client is lazy
    yield
    # Shutdown: engine disposal handled by SQLAlchemy pool


app = FastAPI(
    title="Agent Arena",
    description="Benchmark and reputation layer for on-chain AI agents",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Health check — returns app version and status."""
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "api_version": settings.API_VERSION,
    }


from src.api.router import api_router

app.include_router(api_router)
