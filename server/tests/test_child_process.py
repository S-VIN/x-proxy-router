import ctypes
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

from server.utils import child_process
from server.utils.child_process import start_child_process

ROOT = Path(__file__).resolve().parents[2]

# A server stand-in: starts a long-running child and prints its pid.
PARENT = """
import asyncio, sys
from server.utils import start_child_process

async def main():
    child = await start_child_process(sys.executable, "-c", "import time; time.sleep(60)")
    print(child.pid, flush=True)
    await asyncio.sleep(60)

asyncio.run(main())
"""


def alive(pid: int) -> bool:
    """Whether the process runs; a zombie waiting for its parent does not count."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return False
    return state != "Z"


class ChildProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_output_goes_to_one_pipe(self):
        process = await start_child_process(
            sys.executable,
            "-c",
            "import sys; print('out', flush=True); print('err', file=sys.stderr)",
        )
        assert process.stdout is not None
        output = await process.stdout.read()
        self.assertEqual(await process.wait(), 0)
        self.assertEqual(output.split(), [b"out", b"err"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "PR_SET_PDEATHSIG is Linux only")
    def test_child_stops_when_the_server_is_killed(self):
        parent = subprocess.Popen(
            [sys.executable, "-c", PARENT], cwd=ROOT, stdout=subprocess.PIPE, text=True
        )
        self.addCleanup(parent.wait)
        self.addCleanup(parent.kill)
        assert parent.stdout is not None
        self.addCleanup(parent.stdout.close)
        child = int(parent.stdout.readline())
        self.addCleanup(lambda: alive(child) and os.kill(child, signal.SIGKILL))
        self.assertTrue(alive(child))
        # SIGKILL leaves the server no chance to stop the child itself.
        parent.kill()
        parent.wait()
        deadline = time.monotonic() + 5
        while alive(child) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(alive(child))

    def test_windows_job_limits_layout(self):
        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION is 144 bytes in 64-bit Windows.
        self.assertEqual(ctypes.sizeof(child_process._JobExtendedLimitInformation), 144)
