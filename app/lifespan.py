"""App startup checks; detailed metrics go to logs, never to HTTP responses."""

from contextlib import asynccontextmanager
import json
import logging
import os
import time

from fastapi import FastAPI

from app.embedding_smoke import run_embedding_smoke_test


logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.embedding_model = None
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
    yield
    app.state.embedding_model = None
