"""SSE activity stream: hello on connect, live activity events, non-member 404.

httpx's built-in ASGITransport buffers the whole response body, which never
completes for an infinite SSE stream, so these tests use a minimal streaming
ASGI transport that hands chunks over as the app sends them.
"""

import asyncio
import json

import httpx
import pytest

_DONE = object()


class _QueueStream(httpx.AsyncByteStream):
    def __init__(self, chunks: asyncio.Queue, cleanup):
        self._chunks = chunks
        self._cleanup = cleanup

    async def __aiter__(self):
        while True:
            chunk = await self._chunks.get()
            if chunk is _DONE:
                break
            yield chunk

    async def aclose(self):
        await self._cleanup()


class StreamingASGITransport(httpx.AsyncBaseTransport):
    def __init__(self, app):
        self._app = app

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "headers": [(k.lower(), v) for k, v in request.headers.raw],
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "server": (request.url.host, request.url.port),
            "client": ("127.0.0.1", 123),
            "root_path": "",
        }
        body_chunks = request.stream.__aiter__()
        request_complete = False
        disconnected = asyncio.Event()
        chunks: asyncio.Queue = asyncio.Queue()
        started = asyncio.Event()
        response_info: dict = {"status": 500, "headers": []}

        async def receive():
            nonlocal request_complete
            if request_complete:
                await disconnected.wait()
                return {"type": "http.disconnect"}
            try:
                body = await body_chunks.__anext__()
            except StopAsyncIteration:
                request_complete = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.request", "body": body, "more_body": True}

        async def send(message):
            if message["type"] == "http.response.start":
                response_info["status"] = message["status"]
                response_info["headers"] = message.get("headers", [])
                started.set()
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    chunks.put_nowait(body)
                if not message.get("more_body", False):
                    chunks.put_nowait(_DONE)

        task = asyncio.create_task(self._app(scope, receive, send))

        def _on_done(finished: asyncio.Task):
            if not finished.cancelled():
                finished.exception()  # retrieve to avoid warnings
            started.set()
            chunks.put_nowait(_DONE)

        task.add_done_callback(_on_done)
        await asyncio.wait_for(started.wait(), timeout=10)

        async def cleanup():
            disconnected.set()
            if not task.done():
                try:
                    await asyncio.wait_for(task, timeout=5)
                except TimeoutError:
                    task.cancel()

        return httpx.Response(
            status_code=response_info["status"],
            headers=response_info["headers"],
            stream=_QueueStream(chunks, cleanup),
            request=request,
        )


@pytest.fixture
async def sse_client(asgi_app):
    transport = StreamingASGITransport(asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _next_event(lines) -> dict | None:
    """Collect one SSE event (skipping keepalive comments) from a line iterator."""
    fields: dict = {}
    async for line in lines:
        line = line.rstrip("\r")
        if line == "":
            if fields:
                return fields
            continue
        if line.startswith(":"):
            continue
        key, _, value = line.partition(":")
        fields[key] = value.lstrip(" ")
    return fields or None


async def test_sse_hello_then_live_activity(
    client, sse_client, register, make_group
):
    owner = await register(username="haris")
    friend = await register(username="ali")
    group = await make_group(owner["headers"])
    await client.post(
        "/api/groups/join",
        json={"invite_code": group["invite_code"]},
        headers=friend["headers"],
    )

    async with sse_client.stream(
        "GET",
        f"/api/groups/{group['id']}/activity/sse",
        params={"access_token": owner["token"]},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = response.aiter_lines()

        hello = await asyncio.wait_for(_next_event(lines), timeout=5)
        assert hello is not None
        assert hello["event"] == "hello"
        assert json.loads(hello["data"]) == {"group_id": group["id"]}

        # Another member creates a company while the stream is open.
        create_resp = await client.post(
            f"/api/groups/{group['id']}/companies",
            json={"name": "TechCorp"},
            headers=friend["headers"],
        )
        assert create_resp.status_code == 200

        event = await asyncio.wait_for(_next_event(lines), timeout=5)
        assert event is not None
        assert event["event"] == "activity"
        payload = json.loads(event["data"])
        assert payload["type"] == "company_added"
        assert payload["company_name"] == "TechCorp"
        assert payload["username"] == "ali"
        assert payload["group_id"] == group["id"]


async def test_sse_non_member_404(client, register, make_group):
    owner = await register(username="haris")
    outsider = await register(username="mallory")
    group = await make_group(owner["headers"])
    # Buffered transport is fine here: a 404 response is finite.
    resp = await client.get(
        f"/api/groups/{group['id']}/activity/sse",
        params={"access_token": outsider["token"]},
    )
    assert resp.status_code == 404


async def test_sse_requires_token(client, register, make_group):
    owner = await register(username="haris")
    group = await make_group(owner["headers"])
    resp = await client.get(f"/api/groups/{group['id']}/activity/sse")
    assert resp.status_code == 401
