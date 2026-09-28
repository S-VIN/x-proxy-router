"""Serve the built web client next to the WebSocket endpoint."""

import logging
from pathlib import Path

from aiohttp import web

log = logging.getLogger(__name__)

INDEX_FILE = "index.html"
# Vite puts bundles with content hashes in their names here, so they never change.
IMMUTABLE_PREFIX = "assets/"


def add_static_routes(app: web.Application, root: Path) -> None:
    """Serve files under root for GET and HEAD at any path; / is index.html.

    Register after the other routes: this route matches every path. Paths outside
    root, directories and missing files are 404. A missing build is only logged,
    so the server still works for other clients.
    """
    root = root.resolve()
    if not (root / INDEX_FILE).is_file():
        log.warning("Web client is not built: %s not found", root / INDEX_FILE)

    async def serve(request: web.Request) -> web.StreamResponse:
        relative = request.match_info["path"] or INDEX_FILE
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise web.HTTPNotFound()
        if relative.startswith(IMMUTABLE_PREFIX):
            cache_control = "public, max-age=31536000, immutable"
        else:
            cache_control = "no-cache"
        return web.FileResponse(path, headers={"Cache-Control": cache_control})

    app.router.add_get("/{path:.*}", serve)
