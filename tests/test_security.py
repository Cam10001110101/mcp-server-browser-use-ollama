"""Regressions for browser isolation, injection and resource ownership."""

import asyncio
import json
import os
import sys
import threading
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from playwright.async_api import async_playwright

import server


@pytest.fixture
def browser_resources(monkeypatch):
    page = AsyncMock()
    context = AsyncMock()
    browser = AsyncMock()
    playwright = AsyncMock()
    context.new_page.return_value = page
    browser.new_context.return_value = context
    playwright.chromium.launch.return_value = browser
    start = AsyncMock(return_value=playwright)
    monkeypatch.setattr(server, "async_playwright", Mock(return_value=Mock(start=start)))
    return page, context, browser, playwright, start


async def test_launch_enables_sandbox_and_preserves_local_targets(browser_resources):
    page, _, _, playwright, _ = browser_resources
    session_id = await server.launch_browser_impl("http://localhost:8080")
    assert session_id.isdigit()
    page.goto.assert_awaited_once_with("http://localhost:8080")
    options = playwright.chromium.launch.call_args.kwargs
    assert options["chromium_sandbox"] is True
    assert "--no-sandbox" not in options["args"]
    assert server.pending_launches == 0


async def test_pending_launch_reserves_capacity(browser_resources, monkeypatch):
    page, _, _, _, start = browser_resources
    monkeypatch.setattr(server, "max_sessions", 1)
    entered, release = asyncio.Event(), asyncio.Event()

    async def wait_for_navigation(url):
        entered.set()
        await release.wait()

    page.goto.side_effect = wait_for_navigation
    first = asyncio.create_task(server.launch_browser_impl("https://example.com"))
    try:
        await entered.wait()
        with pytest.raises(RuntimeError, match="Maximum sessions"):
            await server.launch_browser_impl("https://example.com")
        assert start.await_count == 1
    finally:
        release.set()
        await first
    assert len(server.active_sessions) == 1


@pytest.mark.parametrize("stage", ["launch", "context", "page", "viewport", "goto"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_partial_launch_releases_owned_resources(browser_resources, stage, cancelled):
    page, context, browser, playwright, _ = browser_resources
    operations = {
        "launch": playwright.chromium.launch,
        "context": browser.new_context,
        "page": context.new_page,
        "viewport": page.set_viewport_size,
        "goto": page.goto,
    }
    operations[stage].side_effect = asyncio.CancelledError() if cancelled else RuntimeError("failure")
    with pytest.raises(asyncio.CancelledError if cancelled else RuntimeError):
        await server.launch_browser_impl("https://example.com")
    playwright.stop.assert_awaited_once()
    if stage != "launch":
        browser.close.assert_awaited_once()
    if stage in {"page", "viewport", "goto"}:
        context.close.assert_awaited_once()
    if stage in {"viewport", "goto"}:
        page.close.assert_awaited_once()
    assert not server.active_sessions
    assert server.pending_launches == 0


async def test_anyio_request_cancellation_still_cleans_up(browser_resources):
    page, context, browser, playwright, _ = browser_resources
    reached = anyio.Event()

    async def wait_forever(url):
        reached.set()
        await anyio.sleep_forever()

    async def close_after_checkpoint():
        await anyio.sleep(0)

    page.goto.side_effect = wait_forever
    for operation in (page.close, context.close, browser.close, playwright.stop):
        operation.side_effect = close_after_checkpoint
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(server.launch_browser_impl, "https://example.com")
        await reached.wait()
        tasks.cancel_scope.cancel()
    for operation in (page.close, context.close, browser.close, playwright.stop):
        operation.assert_awaited_once()
    assert server.pending_launches == 0
    assert not server.active_sessions


@pytest.mark.parametrize("raw_asyncio", [False, True])
async def test_cancellation_during_driver_start_retains_ownership(browser_resources, raw_asyncio):
    _, _, _, playwright, start = browser_resources
    entered, release = asyncio.Event(), asyncio.Event()

    async def start_driver():
        entered.set()
        await release.wait()
        return playwright

    start.side_effect = start_driver
    if raw_asyncio:
        task = asyncio.create_task(server.launch_browser_impl("https://example.com"))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert server.pending_launches == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(server.launch_browser_impl, "https://example.com")
            await entered.wait()
            tasks.cancel_scope.cancel()
            assert server.pending_launches == 1
            release.set()
    playwright.stop.assert_awaited_once()
    playwright.chromium.launch.assert_not_awaited()
    assert server.pending_launches == 0
    assert not server.active_sessions


@pytest.mark.parametrize("failed_resource", [0, 1, 2])
async def test_cleanup_continues_after_close_error(browser_resources, failed_resource):
    page, context, browser, playwright, _ = browser_resources
    session_id = await server.launch_browser_impl("https://example.com")
    (page, context, browser)[failed_resource].close.side_effect = RuntimeError("already closed")
    await server.close_browser_impl(session_id)
    for operation in (page.close, context.close, browser.close, playwright.stop):
        operation.assert_awaited_once()
    assert not server.active_sessions


async def test_screenshot_never_writes_a_file(browser_resources):
    page, *_ = browser_resources
    session_id = await server.launch_browser_impl("https://example.com")
    page.screenshot.return_value = b"png data"
    assert "8 bytes" in await server.take_screenshot_impl(session_id)
    page.screenshot.assert_awaited_once_with()
    page.screenshot.side_effect = RuntimeError("capture failed")
    with pytest.raises(RuntimeError, match="Screenshot operation failed"):
        await server.take_screenshot_impl(session_id)
    assert all(not call.kwargs for call in page.screenshot.call_args_list)


@pytest.mark.parametrize("pattern", ['"; globalThis.__probe = true; //', 'a "quote"', "a\\b\nline", "</script>"])
async def test_extraction_passes_pattern_as_data(browser_resources, pattern):
    page, *_ = browser_resources
    session_id = await server.launch_browser_impl("https://example.com")
    page.evaluate.return_value = []
    assert json.loads(await server.extract_data_impl(session_id, pattern)) == []
    expression, argument = page.evaluate.call_args.args
    assert argument == pattern
    assert pattern not in expression


async def test_stdio_shutdown_closes_sessions(monkeypatch, browser_resources):
    await server.launch_browser_impl("https://example.com")

    @asynccontextmanager
    async def stdio():
        yield None, None

    monkeypatch.setattr(server, "stdio_server", stdio)
    monkeypatch.setattr(server.server, "run", AsyncMock())
    await server.main()
    assert not server.active_sessions
    browser_resources[3].stop.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.parametrize("entry", ["initialize", "discover"])
async def test_actual_mcp_stdio_protocol(entry):
    """Exercise native July discovery and legacy client compatibility."""
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).parents[1] / "src" / "server.py")],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await getattr(session, entry)()
            tools = await session.list_tools()
            assert len(tools.tools) == 10
            result = await session.call_tool("launch_browser", {"url": "file:///etc/passwd"})
            assert result.is_error
            assert "Only HTTP/HTTPS" in result.content[0].text
            result = await session.call_tool("launch_browser", {"url": 123})
            assert result.is_error
            result = await session.call_tool("no_such_tool", {})
            assert result.is_error


@pytest.mark.e2e
@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Set RUN_BROWSER_TESTS=1 after installing Chromium")
async def test_real_browser_injection_and_legitimate_extraction(monkeypatch):
    """Run the injection payload in an isolated, sandboxed browser on a local page."""
    class PageHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'<html><body><p>an ordinary "quote"</p><svg class="icon"></svg><span class="price">$42</span></body></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), PageHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    playwright = await async_playwright().start()
    original_launch = playwright.chromium.launch

    async def headless_launch(**options):
        options["headless"] = True
        if executable := os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = executable
        return await original_launch(**options)

    monkeypatch.setattr(playwright.chromium, "launch", headless_launch)
    monkeypatch.setattr(server, "async_playwright", Mock(return_value=Mock(start=AsyncMock(return_value=playwright))))
    try:
        sid = await server.launch_browser_impl(f"http://127.0.0.1:{httpd.server_port}")
        page = server.active_sessions[sid].page
        for payload in ['"; globalThis.__probe = true; //', '"; throw new Error("injected"); //', "a\\b\nline"]:
            assert isinstance(json.loads(await server.extract_data_impl(sid, payload)), list)
            assert await page.evaluate("typeof globalThis.__probe") == "undefined"
        ordinary = json.loads(await server.extract_data_impl(sid, 'ordinary "quote"'))
        assert any('ordinary "quote"' in item["text"] for item in ordinary)
        prices = json.loads(await server.extract_data_impl(sid, "PRODUCT PRICES"))
        assert prices[0]["text"] == "$42"
        assert "bytes" in await server.take_screenshot_impl(sid)
        await server.close_browser_impl(sid)
    finally:
        await server.cleanup_all_sessions()
        await playwright.stop()
        httpd.shutdown()
        httpd.server_close()
        thread.join()
