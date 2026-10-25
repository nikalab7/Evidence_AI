import asyncio

from app.main import RequestBodyLimitMiddleware


def test_upload_middleware_rejects_concurrent_write_before_reading_body():
    app_calls = []

    async def downstream(_scope, _receive, _send):
        app_calls.append(True)

    middleware = RequestBodyLimitMiddleware(downstream)
    assert middleware._upload_write_gate.acquire(blocking=False)
    events = []
    receive_calls = []

    async def receive():
        receive_calls.append(True)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        events.append(message)

    scope = {
        "type": "http", "method": "POST", "path": "/api/documents",
        "headers": [(b"content-length", b"0")],
    }
    try:
        asyncio.run(middleware(scope, receive, send))
    finally:
        middleware._upload_write_gate.release()

    assert not app_calls
    assert not receive_calls
    assert next(event["status"] for event in events if event["type"] == "http.response.start") == 429
    assert any((name, value) == (b"retry-after", b"1")
               for event in events if event["type"] == "http.response.start"
               for name, value in event["headers"])


def test_upload_middleware_releases_gate_after_downstream_error():
    async def downstream(_scope, _receive, _send):
        raise RuntimeError("fixture failure")

    middleware = RequestBodyLimitMiddleware(downstream)

    async def receive():
        return {"type": "http.request", "body": b"small", "more_body": False}

    async def send(_message):
        return None

    scope = {
        "type": "http", "method": "POST", "path": "/api/documents",
        "headers": [(b"content-length", b"5")],
    }
    try:
        asyncio.run(middleware(scope, receive, send))
    except RuntimeError as exc:
        assert str(exc) == "fixture failure"
    else:
        raise AssertionError("downstream failure was swallowed")

    assert middleware._upload_write_gate.acquire(blocking=False)
    middleware._upload_write_gate.release()


def test_upload_middleware_coalesces_many_small_asgi_body_fragments():
    source_body = b"x" * 10_000
    fragment_index = 0
    observed = []

    async def downstream(_scope, receive, _send):
        observed.append(await receive())

    async def receive():
        nonlocal fragment_index
        if fragment_index >= len(source_body):
            return {"type": "http.disconnect"}
        start = fragment_index
        fragment_index += 1
        return {
            "type": "http.request",
            "body": source_body[start:fragment_index],
            "more_body": fragment_index < len(source_body),
        }

    async def send(_message):
        return None

    middleware = RequestBodyLimitMiddleware(downstream)
    scope = {
        "type": "http", "method": "POST", "path": "/api/documents",
        "headers": [(b"content-length", str(len(source_body)).encode())],
    }
    asyncio.run(middleware(scope, receive, send))

    assert len(observed) == 1
    assert observed[0] == {
        "type": "http.request", "body": source_body, "more_body": False,
    }
