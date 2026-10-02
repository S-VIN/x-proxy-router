import os
import socket
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from server.main import stops_with_stdin

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class StdinStopTests(unittest.TestCase):
    def test_only_one_turns_it_on(self):
        self.assertTrue(stops_with_stdin({"XPR_STOP_ON_STDIN_CLOSE": " 1 "}))
        for value in ("", "0", "true", "yes"):
            self.assertFalse(stops_with_stdin({"XPR_STOP_ON_STDIN_CLOSE": value}), value)
        self.assertFalse(stops_with_stdin({}))

    def start(self, data: str, **environ: str) -> subprocess.Popen:
        """The real server with the real core, as the desktop application starts it."""
        process = subprocess.Popen(
            [sys.executable, "-m", "server.main"],
            cwd=ROOT,
            env=os.environ
            | {"XPR_UI_HOST": "127.0.0.1", "XPR_UI_PORT": str(free_port()), "XPR_DATA_DIR": data}
            | environ,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        assert process.stdin is not None and process.stdout is not None
        self.addCleanup(process.stdout.close)
        self.addCleanup(process.stdin.close)
        # A server that hangs must not hang the tests.
        watchdog = threading.Timer(30, process.kill)
        watchdog.start()
        self.addCleanup(watchdog.cancel)
        return process

    def wait_started(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        output = []
        for line in process.stdout:
            output.append(line)
            if "Application started" in line:
                return
        self.fail("The server did not start:\n" + "".join(output))

    def test_server_stops_in_order_when_stdin_closes(self):
        data = self.enterContext(TemporaryDirectory())
        process = self.start(data, XPR_STOP_ON_STDIN_CLOSE="1")
        assert process.stdin is not None and process.stdout is not None
        self.wait_started(process)
        # Written data is not a command: only closing the pipe stops the server.
        process.stdin.write("stop\n")
        process.stdin.flush()
        self.assertIsNone(process.poll())
        process.stdin.close()
        output = process.stdout.read()
        self.assertEqual(process.wait(), 0, output)
        self.assertIn("Standard input closed", output)
        self.assertIn("Application stopped", output)
        self.assertTrue((Path(data) / "settings.sqlite3").is_file())

    def test_server_ignores_stdin_without_the_variable(self):
        data = self.enterContext(TemporaryDirectory())
        process = self.start(data)
        assert process.stdin is not None and process.stdout is not None
        self.wait_started(process)
        process.stdin.close()
        with self.assertRaises(subprocess.TimeoutExpired):
            process.wait(timeout=1)
        process.terminate()
        output = process.stdout.read()
        process.wait()
        self.assertIn("Application stopped", output)
