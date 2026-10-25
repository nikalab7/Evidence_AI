"""App startup checks; detailed metrics go to logs, never to HTTP responses."""

from contextlib import asynccontextmanager
import json
import logging
import os
import time

from fastapi import FastAPI

from app.config import Settings
from app.embedding_smoke import (
    MODEL_NAME,
    process_peak_rss_bytes,
    process_rss_bytes,
    run_embedding_smoke_test,
)
from app.llm.gemini_client import GeminiClient
from app.memory_monitor import ProcessMemoryMonitor
from app.model_cache import load_model
from app.rate_limit import InvestigationLimiter


logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.load()
    app.state.settings = settings
    app.state.embedding_model = None
    app.state.gemini_client = None
    app.state.indexed_document_count = settings.indexed_document_count
    app.state.investigation_limiter = InvestigationLimiter(
        daily_budget=settings.investigation_daily_budget,
        per_ip_per_minute=settings.investigation_per_ip_per_minute,
        max_concurrent=settings.investigation_max_concurrent,
    )
    app_start = time.perf_counter()
    enabled = os.getenv("ENABLE_EMBEDDING_STARTUP_CHECK", "false").strip().lower() == "true"
    if enabled:
        try:
            model, report = run_embedding_smoke_test()
        except Exception as exc:
            logger.error(json.dumps({
                "event": "fastembed_startup_check",
                "status": "failed",
                "error_type": type(exc).__name__,
                "startup_elapsed_seconds": round(time.perf_counter() - app_start, 4),
            }, sort_keys=True))
            raise RuntimeError("Embedding startup check failed; see sanitized startup log.") from None
        app.state.embedding_model = model
        report["app_startup_seconds"] = round(time.perf_counter() - app_start, 4)
        logger.info(json.dumps({"event": "fastembed_startup_check", **report}, sort_keys=True))
    else:
        try:
            app.state.embedding_model = load_model(
                os.getenv("FASTEMBED_MODEL", MODEL_NAME), threads=1,
            )
        except Exception as exc:
            logger.error(json.dumps({
                "event": "fastembed_startup_check",
                "status": "failed",
                "error_type": type(exc).__name__,
                "startup_elapsed_seconds": round(time.perf_counter() - app_start, 4),
            }, sort_keys=True))
            raise RuntimeError("Embedding model could not load from the local cache.") from None

    app.state.memory_monitor = ProcessMemoryMonitor()
    app.state.memory_monitor.start()
    app.state.gemini_client = GeminiClient(settings) if settings.gemini_api_key else None
    startup_peak = process_peak_rss_bytes()
    memory_limit = 512 * 1024 * 1024
    logger.info(json.dumps({
        "event": "application_startup_memory",
        "rss_bytes": process_rss_bytes(),
        "peak_rss_bytes": startup_peak,
        "render_free_memory_limit_bytes": memory_limit,
        "startup_peak_below_limit": startup_peak is not None and startup_peak < memory_limit,
        "app_startup_seconds": round(time.perf_counter() - app_start, 4),
        "model_loaded_once": app.state.embedding_model is not None,
        "investigation_daily_budget_enabled": settings.investigation_daily_budget > 0,
    }, sort_keys=True))
    try:
        yield
    finally:
        app.state.embedding_model = None
        if app.state.gemini_client is not None:
            app.state.gemini_client.close()
            app.state.gemini_client = None
        app.state.memory_monitor.stop()
