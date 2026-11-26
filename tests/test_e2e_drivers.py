from __future__ import annotations

import base64
import hashlib
import json
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

E2E = Path(__file__).resolve().parent / "e2e"
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
BANNERS = {"bidi.mjs": "WebDriver BiDi listening on ws://127.0.0.1:{port}", "cdp.mjs": "DevTools listening on ws://127.0.0.1:{port}/devtools/browser/x"}


def silent_server(held: list[socket.socket]) -> int:
    """Args:
        held: receives the accepted connection, kept open and never answered.

    Returns:
        The port of a WebSocket server that completes the handshake and then
        stays silent.
    """
    server = socket.create_server(("127.0.0.1", 0))
    held.append(server)

    def serve() -> None:
        connection, _ = server.accept()
        held.append(connection)
        request = connection.recv(4096).decode()
        key = next(line.split(":", 1)[1].strip() for line in request.split("\r\n") if line.lower().startswith("sec-websocket-key:"))
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        connection.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode())
        while connection.recv(4096):
            pass

    threading.Thread(target=serve, daemon=True).start()
    return server.getsockname()[1]


def close_all(sockets: list[socket.socket]) -> None:
    for item in sockets:
        item.close()


class TestDrivers(unittest.TestCase):
    def test_a_driver_fails_fast_when_the_browser_dies_while_a_command_waits_for_its_answer(self):
        for driver, banner in BANNERS.items():
            with self.subTest(driver=driver), tempfile.TemporaryDirectory() as tmp:
                held: list[socket.socket] = []
                self.addCleanup(close_all, held)
                browser = Path(tmp) / "browser"
                browser.write_text(f"#!/bin/sh\necho '{banner.format(port=silent_server(held))}' >&2\nsleep 2\nexit 3\n", encoding="utf-8")
                browser.chmod(0o755)
                plan = Path(tmp) / "plan.json"
                plan.write_text(json.dumps({"steps": []}), encoding="utf-8")
                done = subprocess.run(["node", str(E2E / driver), str(browser), str(plan)], capture_output=True, text=True, timeout=60, check=False)
                self.assertNotEqual(done.returncode, 0, done.stdout)
                self.assertIn("browser exited with 3", done.stderr)


if __name__ == "__main__":
    unittest.main()
