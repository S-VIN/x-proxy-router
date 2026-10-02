"""Start core binaries so that they do not outlive the server process."""

import asyncio
import ctypes
import logging
import os
import signal
import subprocess
import sys
from collections.abc import Callable

log = logging.getLogger(__name__)

_PR_SET_PDEATHSIG = 1
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
# The watcher process of macOS: stops the process named in its argument when the
# pipe from the server closes, which the OS does when the server exits.
_WATCHER = """
import os, signal, sys
while os.read(0, 4096):
    pass
try:
    os.kill(int(sys.argv[1]), signal.SIGTERM)
except ProcessLookupError:
    pass
"""


async def start_child_process(
    *command: str, env: dict[str, str] | None = None
) -> asyncio.subprocess.Process:
    """Start a child with stdin closed and stdout and stderr in one pipe.

    Normally the owner stops the child; if the server exits without that (killed,
    crashed, terminal closed), the OS stops it. On Linux the child gets SIGTERM
    when the server dies (PR_SET_PDEATHSIG); call this from the event loop
    thread, since the signal follows the thread that started the child. On
    Windows the child joins a job object that is killed when the server exits,
    and no console window opens. macOS has neither: a watcher process sends the
    child SIGTERM when the server is gone.
    """
    linux = sys.platform.startswith("linux")
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        preexec_fn=_stop_with_parent() if linux else None,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if not linux:
        try:
            if sys.platform == "win32":
                _add_to_job(process.pid)
            else:
                _stop_after_server(process)
        except OSError:
            log.warning("The child process %s may outlive the server", process.pid, exc_info=True)
    return process


def _stop_with_parent() -> Callable[[], None]:
    """preexec_fn for Linux: SIGTERM to the child when this process dies."""
    prctl = ctypes.CDLL(None, use_errno=True).prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    parent = os.getpid()

    def set_signal() -> None:
        # Runs in the child between fork and exec.
        prctl(_PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
        # The parent may have died before prctl; then no signal will come.
        if os.getppid() != parent:
            os._exit(1)

    return set_signal


# The tasks of _end_watcher: the event loop keeps only weak references to tasks.
_watchers: set[asyncio.Task[None]] = set()


def _stop_after_server(process: asyncio.subprocess.Process) -> None:
    """Start a watcher that stops the child when the server exits without doing it."""
    watcher = subprocess.Popen(
        [sys.executable, "-I", "-S", "-c", _WATCHER, str(process.pid)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # Ctrl+C in the terminal of the server must not stop the watcher.
        start_new_session=True,
    )
    task = asyncio.get_running_loop().create_task(_end_watcher(process, watcher))
    _watchers.add(task)
    task.add_done_callback(_watchers.discard)


async def _end_watcher(
    process: asyncio.subprocess.Process, watcher: subprocess.Popen[bytes]
) -> None:
    """End the watcher of a child that exited: its pid may go to another process."""
    try:
        await process.wait()
    finally:
        # Cancelled while the child runs: the server exits, the watcher stops the child.
        if process.returncode is not None:
            watcher.kill()
            watcher.wait()
            assert watcher.stdin is not None
            watcher.stdin.close()


class _JobBasicLimitInformation(ctypes.Structure):
    # JOBOBJECT_BASIC_LIMIT_INFORMATION of the Windows API
    _fields_ = [
        ("per_process_user_time_limit", ctypes.c_int64),
        ("per_job_user_time_limit", ctypes.c_int64),
        ("limit_flags", ctypes.c_uint32),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority_class", ctypes.c_uint32),
        ("scheduling_class", ctypes.c_uint32),
    ]


class _JobExtendedLimitInformation(ctypes.Structure):
    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION; IO_COUNTERS is six 64-bit counters.
    _fields_ = [
        ("basic", _JobBasicLimitInformation),
        ("io_info", ctypes.c_uint64 * 6),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    _kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    _kernel32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    _kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    _kernel32.OpenProcess.restype = ctypes.c_void_p
    _kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    # Handle of the job with every child; see _add_to_job.
    _job: int | None = None

    def _checked(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def _add_to_job(pid: int) -> None:
        """Put the process in a job that Windows kills when the server exits.

        The job handle is never closed explicitly: Windows closes it when the
        server exits, and the children go with it. Children do not inherit it.
        """
        global _job
        if _job is None:
            job = _checked(_kernel32.CreateJobObjectW(None, None))
            info = _JobExtendedLimitInformation()
            info.basic.limit_flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            _checked(
                _kernel32.SetInformationJobObject(
                    job,
                    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                    ctypes.byref(info),
                    ctypes.sizeof(info),
                )
            )
            _job = job
        process = _checked(
            _kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        )
        try:
            _checked(_kernel32.AssignProcessToJobObject(_job, process))
        finally:
            _kernel32.CloseHandle(process)
