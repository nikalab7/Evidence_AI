"""FastAPI application entry point."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.lifespan import lifespan

from app.api.health import router as health_router
from app.api.investigations import router as investigations_router
from app.api.pages import router as pages_router


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
app.include_router(pages_router)
app.include_router(investigations_router)


class InvestigationBodyLimitMiddleware:
    """Cap JSON request buffering even when Content-Length is absent or false."""

    def __init__(self, app: ASGIApp, *, max_bytes: int = 16_384) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (scope["type"] != "http" or scope.get("path") != "/api/investigate"
                or scope.get("method") != "POST"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        try:
            content_length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            content_length = self.max_bytes + 1
        if content_length > self.max_bytes:
            await JSONResponse(
                status_code=413, content={"detail": "Investigation request body is too large."},
            )(scope, receive, send)
            return

        messages = []
        body_bytes = 0
        while True:
            message = await receive()
            if message["type"] == "http.request":
                body_bytes += len(message.get("body", b""))
                if body_bytes > self.max_bytes:
                    await JSONResponse(
                        status_code=413,
                        content={"detail": "Investigation request body is too large."},
                    )(scope, receive, send)
                    return
            messages.append(message)
            if message["type"] == "http.disconnect" or not message.get("more_body", False):
                break

        buffered = iter(messages)

        async def replay_receive():
            try:
                return next(buffered)
            except StopIteration:
                return await receive()

        await self.app(scope, replay_receive, send)


app.add_middleware(InvestigationBodyLimitMiddleware)


@app.exception_handler(RequestValidationError)
async def invalid_request_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Question request is invalid. Use 3-1000 characters and a supported retrieval mode.",
        },
    )
