"""App: a browser page that hosts the MCP App view, its sandbox proxy, and the MCP server it renders the view from."""

from html import escape
from pathlib import Path
import socket
import threading

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from mcp.server import Server
import uvicorn

from reality_check.core.skill import repository_url, version
from reality_check.schemas import RealityCheckError

STATIC = Path(__file__).parent / "static"
VIEW = STATIC / "view" / "mcp_app.html"
HOST_STATIC = STATIC / "host"
BUILD_COMMAND = "uv run build-app.py"
HOST = "127.0.0.1"
STOP_TIMEOUT_SECONDS = 5
# The MCP Apps spec's restrictive default for a view that declares no `ui.csp`, which every host must allow, so evidence
# that shows here shows in them. The one addition is `data:` fonts; a host without it shows the view in system fonts.
# The view is written into a frame of the sandbox page, so it inherits this policy.
VIEW_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self' data:; media-src 'self' data:; connect-src 'none'; frame-src 'none'; object-src 'none'; "
    "base-uri 'self'"
)


class App:
    """The app being served: where to open it in a browser."""

    def __init__(self, url: str, servers: list[uvicorn.Server], threads: list[threading.Thread]) -> None:
        self.url = url
        self._servers = servers
        self._threads = threads

    def stop(self) -> None:
        """Disconnect every page and stop serving."""
        for server in self._servers:
            server.should_exit = True
        for thread in self._threads:
            thread.join(STOP_TIMEOUT_SECONDS)


def view() -> str:
    """The view's HTML: the MCP App resource every host renders, with the tool's version and where its docs are."""
    if not VIEW.is_file():
        raise RealityCheckError(
            code="app-not-built",
            message=f"The app's view is not built: {VIEW} does not exist.",
            remedy=f"Run `{BUILD_COMMAND}` from the repository root, or install a released version of the tool.",
        )
    html = VIEW.read_text(encoding="utf-8")
    return html.replace("{{version}}", escape(version())).replace("{{repository}}", escape(repository_url() or ""))


def serve_app(server: Server, port: int | None = None) -> App:
    """Serve the browser host page for `server`'s view from daemon threads, and return once both ports listen."""
    # Bound and listening before this returns, so the URL answers at once and a held port is a named failure.
    host_sock = _bind(port)
    try:
        sandbox_sock = _bind(None)
    except RealityCheckError:
        host_sock.close()
        raise
    host_port = int(host_sock.getsockname()[1])
    sandbox_port = int(sandbox_sock.getsockname()[1])
    apis = (_create_host_api(server, sandbox_port), _create_sandbox_api(host_port))
    servers: list[uvicorn.Server] = []
    threads: list[threading.Thread] = []
    for api, sock in zip(apis, (host_sock, sandbox_sock), strict=True):
        # Without a log config uvicorn leaves logging alone. Its default one writes access lines to stdout, which the
        # MCP adapter needs for MCP messages alone.
        uvicorn_server = uvicorn.Server(uvicorn.Config(api, log_config=None, log_level="warning"))
        thread = threading.Thread(target=uvicorn_server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        servers.append(uvicorn_server)
        threads.append(thread)
    return App(f"http://{HOST}:{host_port}", servers, threads)


def _create_host_api(server: Server, sandbox_port: int) -> FastAPI:
    # The SDK guards `/mcp` against DNS rebinding for a loopback host by default, so only this machine's pages reach it.
    mcp_api = server.streamable_http_app(host=HOST)
    # FastAPI runs only its own lifespan, never a mounted app's, and the session manager must be running to serve.
    api = FastAPI(lifespan=lambda _: server.session_manager.run(), docs_url=None, redoc_url=None, openapi_url=None)
    api.router.routes.extend(mcp_api.routes)

    @api.get("/{page_path:path}", include_in_schema=False)
    def page(page_path: str) -> Response:
        index = HOST_STATIC / "index.html"
        if not index.is_file():
            return _not_built()
        candidate = (HOST_STATIC / page_path).resolve()
        if candidate.is_relative_to(HOST_STATIC.resolve()) and candidate.is_file() and candidate.suffix != ".html":
            return FileResponse(candidate)
        return HTMLResponse(index.read_text(encoding="utf-8").replace("{{sandbox_port}}", str(sandbox_port)))

    return api


def _create_sandbox_api(host_port: int) -> FastAPI:
    """The sandbox proxy page, on its own origin as the MCP Apps spec requires of a web host, with the view's CSP."""
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @api.get("/sandbox.html", include_in_schema=False)
    def sandbox() -> Response:
        page = HOST_STATIC / "sandbox.html"
        if not page.is_file():
            return _not_built()
        return HTMLResponse(
            page.read_text(encoding="utf-8").replace("{{host_port}}", str(host_port)),
            headers={"Content-Security-Policy": VIEW_CSP, "Cache-Control": "no-store"},
        )

    @api.get("/assets/{asset}", include_in_schema=False)
    def asset(asset: str) -> Response:
        assets = (HOST_STATIC / "assets").resolve()
        candidate = (assets / asset).resolve()
        if candidate.is_relative_to(assets) and candidate.is_file():
            return FileResponse(candidate)
        return PlainTextResponse("Not found.", status_code=404)

    return api


def _not_built() -> Response:
    return PlainTextResponse(f"The app is not built. Run `{BUILD_COMMAND}` from the repository root.", status_code=503)


def _bind(port: int | None) -> socket.socket:
    # SO_REUSEADDR stays off: on Windows it lets a second app bind a port the first still holds.
    sock = socket.socket(socket.AF_INET)
    try:
        sock.bind((HOST, port or 0))
    except OSError as error:
        sock.close()
        raise RealityCheckError(
            code="port-held",
            message=f"The app could not bind {HOST}:{port}: {error.strerror or error}.",
            remedy="Omit the port to have a free one chosen, or pass one nothing else holds.",
        ) from error
    sock.listen()
    return sock
