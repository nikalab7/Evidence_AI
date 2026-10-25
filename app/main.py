"""FastAPI application entry point."""

from threading import Lock

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.lifespan import lifespan

from app.api.health import router as health_router
from app.api.documents import router as documents_router
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
app.include_router(documents_router)
app.include_router(pages_router)
app.include_router(investigations_router)


class RequestBodyLimitMiddleware:
    """Bound request buffering for investigations and multipart document writes."""

    def __init__(self, app: ASGIApp, *, max_bytes: int = 16_384) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self._upload_write_gate = Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path, method = scope.get("path", ""), scope.get("method", "")
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_upload_write = (
            (path == "/api/documents" and method == "POST")
            or (path.startswith("/api/documents/") and method == "PUT")
        )
        if path == "/api/investigate" and method == "POST":
            body_limit = self.max_bytes
            error_detail = "Investigation request body is too large."
        elif is_upload_write:
            # A single file is capped at 5 MiB; this allowance covers multipart
            # boundaries and the short title/strategy fields.
            body_limit = 5 * 1024 * 1024 + 64 * 1024
            error_detail = "Document request body is too large."
        else:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        try:
            content_length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            content_length = body_limit + 1
        if content_length > body_limit:
            await JSONResponse(
                status_code=413, content={"detail": error_detail},
            )(scope, receive, send)
            return

        if is_upload_write and not self._upload_write_gate.acquire(blocking=False):
            await JSONResponse(
                status_code=429,
                content={
                    "detail": "Another document upload or update is in progress. Please retry shortly."
                },
                headers={"Retry-After": "1"},
            )(scope, receive, send)
            return

        try:
            body = bytearray()
            disconnected = False
            body_bytes = 0
            while True:
                asgi_message = await receive()
                if asgi_message["type"] == "http.disconnect":
                    disconnected = True
                    break
                if asgi_message["type"] == "http.request":
                    chunk = asgi_message.get("body", b"")
                    body_bytes += len(chunk)
                    if body_bytes > body_limit:
                        await JSONResponse(
                            status_code=413,
                            content={"detail": error_detail},
                        )(scope, receive, send)
                        return
                    body.extend(chunk)
                    if not asgi_message.get("more_body", False):
                        break

            body_content = bytes(body)
            replayed = False

            async def replay_receive():
                nonlocal replayed
                if replayed:
                    return await receive()
                replayed = True
                if disconnected:
                    return {"type": "http.disconnect"}
                return {
                    "type": "http.request", "body": body_content, "more_body": False,
                }

            await self.app(scope, replay_receive, send)
        finally:
            if is_upload_write:
                self._upload_write_gate.release()


app.add_middleware(RequestBodyLimitMiddleware)


@app.exception_handler(RequestValidationError)
async def invalid_request_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": "The request is invalid. Check the required fields and supported values.",
        },
    )
