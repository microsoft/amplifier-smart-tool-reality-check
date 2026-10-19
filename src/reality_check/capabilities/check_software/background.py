"""The process a detached check runs in: its request on stdin, one report on stdout once its agent runs, then the check.

`check_software(detach=True)` starts it apart from the caller, so the check outlives the caller.
"""

import asyncio
from collections.abc import Generator
import contextlib
import json
import os
from pathlib import Path
import signal
import sys
from types import FrameType
from typing import Any, TextIO

from reality_check.capabilities.check_software import check
from reality_check.capabilities.check_software.record import PROCESS_LOG
from reality_check.intelligence.interface import Intelligence
from reality_check.schemas import RealityCheckError

# Set in the process that runs the check. The process the caller starts only starts that one, with the same pipes,
# and exits, so the check descends from nothing a caller's process tree takes down with it when it is ended.
RUNNING = "REALITY_CHECK_DETACHED_RUN"
# Every signal that ends the process cancels the check first, so its session stays resumable. SIGBREAK is Windows'
# Ctrl+Break, which reaches a process group of its own.
STOPPING_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK")


def main(intelligence: Intelligence | None = None) -> int:
    """Run the check the request on stdin asks for, to its end; `intelligence` stands in for the agent's in tests."""
    if RUNNING not in os.environ:
        try:
            command = [sys.executable, *sys.orig_argv[1:]]
            check.detached_process(command, sys.stdin, sys.stdout, {**os.environ, RUNNING: "1"})
        except OSError as error:
            _report(sys.stdout, _start_failed(error))
            return 1
        return 0
    # Not passed on to the agent, so a check its agent starts with detach is detached in turn.
    del os.environ[RUNNING]
    # The report goes out on a copy of stdout, and stdout itself goes nowhere until the check runs, so nothing else
    # printed can garble the report.
    report = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    sys.stdout.flush()
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    request = check.DetachedCheckRequest.model_validate_json(sys.stdin.buffer.read())
    return asyncio.run(_run(request, intelligence, report))


async def _run(request: check.DetachedCheckRequest, intelligence: Intelligence | None, report: TextIO) -> int:
    with report:
        try:
            run = await check.start_detached(request, intelligence)
        except RealityCheckError as error:
            _report(report, _failure(error))
            return 1
        except Exception as error:  # whatever stopped it, the caller is waiting to hear
            _report(report, _start_failed(error))
            return 1
        _log_to(run.directory / PROCESS_LOG)
        try:
            await run.running()
        except RealityCheckError as error:
            _report(report, {**_failure(error), "check_id": run.check_id})
            return 1
        _report(report, {"check_id": run.check_id, "directory": str(run.directory)})
    with _stopped_by_signals(run):
        try:
            result = await run.result()
        except RealityCheckError:
            return 1
    return 0 if result.status == "done" else 1


def _failure(error: RealityCheckError) -> dict[str, str]:
    return {"code": error.code, "message": error.message, "remedy": error.remedy}


def _start_failed(error: BaseException) -> dict[str, str]:
    return {
        "code": "check-start-failed",
        "message": f"The process that runs the check did not start it: {type(error).__name__}: {error}",
        "remedy": "Run the check without detach to see why.",
    }


def _report(report: TextIO, message: dict[str, str]) -> None:
    report.write(json.dumps(message) + "\n")
    report.flush()


def _log_to(path: Path) -> None:
    """Send what this process and its children print from now on to the check's log, beside its events."""
    sys.stdout.flush()
    sys.stderr.flush()
    log = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    os.dup2(log, sys.stdout.fileno())
    os.dup2(log, sys.stderr.fileno())
    os.close(log)


@contextlib.contextmanager
def _stopped_by_signals(run: check.CheckRun) -> Generator[None]:
    loop = asyncio.get_running_loop()
    stopping: set[asyncio.Task[None]] = set()

    def stop() -> None:
        task = asyncio.ensure_future(run.cancel())
        stopping.add(task)
        task.add_done_callback(stopping.discard)

    def handler(signum: int, frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(stop)

    previous: dict[signal.Signals, Any] = {}
    for name in STOPPING_SIGNALS:
        number = getattr(signal, name, None)
        if isinstance(number, signal.Signals):
            previous[number] = signal.signal(number, handler)
    try:
        yield
    finally:
        for number, original in previous.items():
            signal.signal(number, original)


if __name__ == "__main__":
    raise SystemExit(main())
