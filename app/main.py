"""FastAPI application entry point."""

from fastapi import FastAPI
from app.lifespan import lifespan

from app.api.health import router as health_router


app = FastAPI(
    title="EvidenceAI",
    version="0.1.0",
    description="Multi-hop AI investigation engine with evidence-backed answers.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.include_router(health_router)
