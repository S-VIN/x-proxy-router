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


async def start_child_process(
    *command: str, env: dict[str, str] | None = None
) -> asyncio.subprocess.Process:
    """Start a child with stdin closed and stdout and stderr in one pipe.

    Normally the owner stops the child; if the server exits without that (killed,
    crashed, terminal closed), the OS stops it. On Linux the child gets SIGTERM
    when the server dies (PR_SET_PDEATHSIG); call this from the event loop
    thread, since the signal follows the thread that started the child. On
    Windows the child joins a job object that is killed when the server exits,
    and no console window opens.
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        preexec_fn=_stop_with_parent() if sys.platform.startswith("linux") else None,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if sys.platform == "win32":
        try:
            _add_to_job(process.pid)
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
