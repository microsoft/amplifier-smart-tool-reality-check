"""MCP adapter: the app's MCP server over stdio, a thin surface over the library."""

import asyncio
from pathlib import Path

from mcp.server.stdio import stdio_server

from reality_check import lib


def run_stdio(directory: Path | None = None) -> None:
    """Serve the MCP server over stdin and stdout until the client disconnects, then stop the app if it was opened.

    Args:
        directory: A checks directory to add to the projects the app shows, and to open on its newest check.
    """
    asyncio.run(_serve(directory))


async def _serve(directory: Path | None) -> None:
    app_server = lib.app_server(directory)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app_server.server.run(read_stream, write_stream, app_server.server.create_initialization_options())
    finally:
        app_server.close()
