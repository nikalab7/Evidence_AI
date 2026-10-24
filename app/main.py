"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.health import router as health_router


app = FastAPI(
    title="EvidenceAI",
    version="0.1.0",
    description="Multi-hop AI investigation engine with evidence-backed answers.",
)
app.include_router(health_router)
