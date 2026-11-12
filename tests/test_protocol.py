"""Exercise July 2026 messages directly, independently of client SDK serialization."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from client import MCPClient

VERSION = "2026-07-28"
PREFIX = "io.modelcontextprotocol/"
SERVER = Path(__file__).parents[1] / "src" / "server.py"


def request(method, params=None, *, version=VERSION, request_id=1):
    return {
        "jsonrpc": "2.0", "id": request_id, "method": method,
        "params": {
            "_meta": {
                PREFIX + "protocolVersion": version,
                PREFIX + "clientCapabilities": {},
                PREFIX + "clientInfo": {"name": "protocol-test", "version": "1"},
            },
            **(params or {}),
        },
    }


@pytest.fixture
async def peer(tmp_path):
    with (tmp_path / "stderr.log").open("wb") as stderr:
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(SERVER), cwd=tmp_path,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr,
        )
        async def exchange(message):
            process.stdin.write(json.dumps(message).encode() + b"\n")
            await process.stdin.drain()
            line = await asyncio.wait_for(process.stdout.readline(), timeout=30)
            assert line, (tmp_path / "stderr.log").read_text()
            result = json.loads(line)
            assert result["id"] == message["id"]
            return result
        try:
            yield exchange
        finally:
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()
                await process.wait()
                pytest.fail("Server did not exit on stdin EOF")


def complete(response):
    assert response["jsonrpc"] == "2.0"
    result = response["result"]
    assert result["resultType"] == "complete"
    assert result["_meta"][PREFIX + "serverInfo"] == {"name": "browser-automation", "version": "0.1.0"}
    return result


async def test_native_discovery_and_tool_schemas(peer):
    # A valid request can precede discovery; initialize is never sent.
    catalog = complete(await peer(request("tools/list")))
    assert catalog["cacheScope"] == "private"
    assert catalog["ttlMs"] == 0
    assert len(catalog["tools"]) == 10
    assert catalog == complete(await peer(request("tools/list", request_id=2)))
    for tool in catalog["tools"]:
        Draft202012Validator.check_schema(tool["inputSchema"])
    discovered = complete(await peer(request("server/discover", request_id=3)))
    assert VERSION in discovered["supportedVersions"]
    assert set(discovered["capabilities"]) == {"tools"}


async def test_versions_and_errors_are_request_scoped(peer):
    error = (await peer(request("tools/list", version="2099-01-01")))["error"]
    assert error["code"] == -32022
    assert VERSION in error["data"]["supported"]
    complete(await peer(request("tools/list", request_id=2)))
    assert (await peer(request("does/not/exist")))["error"]["code"] == -32601
    for arguments in ({"url": "file:///synthetic-forbidden-path"}, {"url": 123}, {}):
        result = complete(await peer(request("tools/call", {"name": "launch_browser", "arguments": arguments})))
        assert result["isError"] is True
        assert result["content"][0]["type"] == "text"
    # State is addressed by an explicit application handle, not an MCP session.
    result = complete(await peer(request("tools/call", {"name": "close_browser", "arguments": {"session_id": "missing"}})))
    assert result["isError"] is True


async def test_bundled_client_uses_native_discovery():
    client = MCPClient()
    try:
        await client.connect_to_server(str(SERVER))
        assert client.session.discover_result is not None
        assert client.session.initialize_result is None
        assert VERSION in client.session.discover_result.supported_versions
        assert len(client.tools) == 10
    finally:
        await client.exit_stack.aclose()
