"""The MCP adapter on the wire, spoken to over stdio the way MCP clients and MCP Apps hosts speak to it."""

from collections.abc import Callable, Iterator
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from typing import Any

from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
import pytest

from reality_check.capabilities.app.tools import VIEW_URI

TIMEOUT_SECONDS = 10
PROTOCOL_VERSION = "2025-11-25"
MCP_APPS_HOST = {"extensions": {EXTENSION_ID: {"mimeTypes": [APP_MIME_TYPE]}}}
VIEW_TOOLS = ("list_checks", "read_check", "read_check_activity", "open_check_folder")


class Wire:
    """One `reality-check mcp` process, spoken to in newline-delimited JSON-RPC on the initialize handshake."""

    def __init__(self, home: Path) -> None:
        # Its own home, so the process reads and writes no registry but the test's.
        environment = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "reality_check.cli", "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.next_id = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.messages.put(json.loads(line))

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def receive(self, matches: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        while True:
            message = self.messages.get(timeout=TIMEOUT_SECONDS)
            if matches(message):
                return message

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.next_id += 1
        request_id = self.next_id
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return self.receive(lambda message: message.get("id") == request_id and "method" not in message)["result"]

    def initialize(self, capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": capabilities or {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        )
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})


@pytest.fixture
def wire(tmp_path: Path) -> Iterator[Wire]:
    server = Wire(tmp_path)
    yield server
    if server.process.poll() is None:
        server.process.kill()


def text_of(result: dict[str, Any]) -> str:
    return "\n".join(block["text"] for block in result["content"])


def test_a_client_without_mcp_apps_sees_only_open_app(wire: Wire) -> None:
    initialized = wire.initialize()
    tools = {tool["name"]: tool for tool in wire.request("tools/list", {})["tools"]}
    opened = text_of(wire.call_tool("open_app", {}))

    assert set(tools) == {"open_app"}
    assert tools["open_app"]["_meta"] == {"ui": {"resourceUri": VIEW_URI}}
    assert tools["open_app"]["annotations"] == {
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert "open_app" in initialized["instructions"]
    assert wire.request("resources/list", {})["resources"] == []
    assert wire.request("resources/templates/list", {})["resourceTemplates"] == []
    assert opened.startswith("Give the user this URL to open the app: http://127.0.0.1:")


def test_an_mcp_apps_host_gets_the_view_the_read_only_tools_it_calls_and_the_evidence_files(wire: Wire) -> None:
    wire.initialize(MCP_APPS_HOST)
    tools = {tool["name"]: tool for tool in wire.request("tools/list", {})["tools"]}
    resources = wire.request("resources/list", {})["resources"]
    templates = wire.request("resources/templates/list", {})["resourceTemplates"]
    listed = wire.call_tool("list_checks", {})
    opened = text_of(wire.call_tool("open_app", {}))

    assert set(tools) == {"open_app", *VIEW_TOOLS}
    assert all(tools[name]["_meta"]["ui"]["visibility"] == ["app"] for name in VIEW_TOOLS)
    assert [resource["uri"] for resource in resources] == [VIEW_URI]
    assert [template["uriTemplate"] for template in templates] == [
        "reality-check://checks/{checks_directory}/{check_id}/{+path}"
    ]
    assert {key: value for key, value in listed["structuredContent"].items() if key != "can_open_folders"} == {
        "checks": [],
        "focus": None,
        "opened": 0,
    }
    assert "inline" in opened
