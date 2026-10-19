"""A checks directory on disk: each check's check.json, its events, and whether the process running it is alive."""

from pathlib import Path
import re
import tempfile
import time

import psutil
from pydantic import ValidationError

from reality_check.schemas import CheckEvent, CheckRecord, CheckState, RealityCheckError

EVENTS = "events.jsonl"
RECORD = "check.json"
# Where a detached check's process writes once the check runs, beside its events.
PROCESS_LOG = "process.log"
# The agent provider's own state for this check's session, opaque to everything but that provider's implementation.
SESSION = "session"
CHECK_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
# Windows refuses to replace a file another process has open, such as a reader of check.json, and to open one being
# replaced; both are brief.
REPLACE_ATTEMPTS = 20
REPLACE_WAIT_SECONDS = 0.05
# A process's start time can differ by rounding between reads; a process that takes over a dead one's pid starts well
# after it.
START_TOLERANCE_SECONDS = 1.0


def load_record(root: Path, check_id: str) -> CheckRecord:
    """The record of the check `check_id` in the checks directory `root`."""
    path = root / check_id / RECORD
    if not CHECK_ID_PATTERN.match(check_id) or not path.is_file():
        known = sorted(found.parent.name for found in root.glob(f"*/{RECORD}"))[-5:]
        raise RealityCheckError(
            code="check-not-found",
            message=f"No check {check_id!r} in {root}.",
            remedy=f"Name a check_id from that directory (the latest: {', '.join(known) or 'none'}), or pass the "
            "checks directory the check was started with.",
        )
    return CheckRecord.model_validate_json(read_atomically(path))


def write_record(directory: Path, record: CheckRecord) -> None:
    write_atomically(directory / RECORD, record.model_dump_json(indent=2))


def read_atomically(path: Path) -> str:
    # Windows refuses to open a file in the moment another process replaces it, as write_atomically does.
    for _ in range(REPLACE_ATTEMPTS - 1):
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            time.sleep(REPLACE_WAIT_SECONDS)
    return path.read_text(encoding="utf-8")


def write_atomically(path: Path, text: str) -> None:
    # Written aside and renamed, because other processes read it while this one writes it. Each write has a file of its
    # own to rename, so two at once never take each other's.
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as file:
        partial = Path(file.name)
        file.write(text)
    try:
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                partial.replace(path)
                return
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_WAIT_SECONDS)
    finally:
        partial.unlink(missing_ok=True)


def read_events(path: Path, offset: int = 0) -> tuple[list[CheckEvent], int]:
    """The events in a check's events.jsonl past `offset`, and the offset to read on from.

    Only whole lines are read, so a line the check is still writing waits for the next read.
    """
    try:
        with path.open("rb") as events:
            events.seek(offset)
            data = events.read()
    except FileNotFoundError:
        return [], offset
    end = data.rfind(b"\n") + 1
    try:
        read = [CheckEvent.model_validate_json(line) for line in data[:end].splitlines() if line.strip()]
    except ValidationError as error:
        raise RealityCheckError(
            code="bad-events",
            message=f"{path} holds a line that is not a check event: {error.errors()[0]['msg']}.",
            remedy="Remove that line, or read another check.",
        ) from None
    return read, offset + end


def process_started(pid: int) -> float | None:
    """When the process `pid` started, in seconds since the machine booted, or None when there is no such process."""
    try:
        return _since_boot(psutil.Process(pid))
    except psutil.Error:
        return None


def alive(pid: int, started: float | None) -> bool:
    """Whether the process `pid` runs and is the one that started at `started`, when that is known."""
    try:
        process = psutil.Process(pid)
        if process.status() == psutil.STATUS_ZOMBIE:
            return False
        created = _since_boot(process)
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        # It exists, but belongs to another user, so its start time cannot be compared.
        return True
    return started is None or abs(created - started) < START_TOLERANCE_SECONDS


def check_state(record: CheckRecord) -> CheckState:
    """The check's status, or `crashed` when its record says running and its process is gone.

    A record without a pid, written before checks kept one, counts as alive.
    """
    if record.status == "running" and record.pid is not None and not alive(record.pid, record.pid_started):
        return "crashed"
    return record.status


def _since_boot(process: psutil.Process) -> float:
    # Relative to boot, because the wall-clock start time shifts with the boot time the platform reports, which WSL
    # moves by whole seconds between reads.
    return process.create_time() - psutil.boot_time()
