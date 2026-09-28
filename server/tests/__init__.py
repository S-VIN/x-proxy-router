"""Server tests. Applications started by tests listen on a free WebSocket port
and do not serve the web client."""

import server.main

server.main.WEBSOCKET_PORT = 0
server.main.WEB_CLIENT_DIR = None
