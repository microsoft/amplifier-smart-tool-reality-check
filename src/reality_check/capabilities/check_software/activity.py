"""A check's activity: what was asked of it, what its agent said, thought, and did, steering, and how it ended."""

from pathlib import Path

from reality_check.capabilities.check_software.record import EVENTS, PROCESS_LOG, check_state, load_record, read_events
from reality_check.schemas import (
    DEFAULT_CHECKS_DIRECTORY,
    FULL_FIELDS,
    ActivityEntry,
    CheckActivity,
    CheckEvent,
    CheckRecord,
    RealityCheckError,
)


def read_check_activity(
    check_id: str,
    after: int | None = None,
    tool_call_id: str | None = None,
    checks_directory: Path = DEFAULT_CHECKS_DIRECTORY,
) -> CheckActivity:
    """The check as it stands and its activity, only what came after the cursor `after`, or only one tool call in full."""
    root = checks_directory.resolve()
    record = load_record(root, check_id)
    directory = root / check_id
    path = directory / EVENTS
    offset = after or 0
    if after is not None:
        _require_cursor(path, after, check_id)
    events, cursor = read_events(path, offset)
    if tool_call_id is None:
        entries = [_entry(event, record, directory) for event in events]
    else:
        entries = [
            _tool_entry(event, full=True)
            for event in events
            if event.kind == "tool" and event.data.get("tool_call_id") == tool_call_id
        ]
        if not entries:
            raise RealityCheckError(
                code="tool-call-not-found",
                message=f"Check {check_id} has no tool call {tool_call_id!r}" + (f" after {after}." if after else "."),
                remedy=f"Take a `tool_call_id` from a `tool` entry of `reality-check read-check-activity --check-id "
                f"{check_id}`.",
            )
    log = directory / PROCESS_LOG
    return CheckActivity(
        check=record,
        state=check_state(record),
        process_log=log if log.is_file() else None,
        entries=entries,
        cursor=cursor,
    )


def _require_cursor(path: Path, after: int, check_id: str) -> None:
    """Raise unless `after` is where a line of the check's events starts, as a cursor from an earlier read is."""
    size = path.stat().st_size if path.is_file() else 0
    valid = 0 <= after <= size
    if valid and after > 0:
        with path.open("rb") as events:
            events.seek(after - 1)
            valid = events.read(1) == b"\n"
    if not valid:
        raise RealityCheckError(
            code="bad-cursor",
            message=f"{after} is not a cursor into check {check_id}'s activity.",
            remedy="Read it without after, then pass the cursor that read returns.",
        )


def _entry(event: CheckEvent, record: CheckRecord, directory: Path) -> ActivityEntry:
    data = event.data
    match event.kind:
        case "started":
            started = dict(data)
            if isinstance(started.get("agent_request"), dict):
                started["agent_request"] = {
                    key: value for key, value in started["agent_request"].items() if key != "initial_message"
                }
            return ActivityEntry(
                time=event.time, kind="request", text=record.request, origin=record.origin, data=started
            )
        case "progress":
            return ActivityEntry(time=event.time, kind="said", text=event.text, data=data)
        case "reasoning":
            return ActivityEntry(time=event.time, kind="reasoning", text=event.text, data=data)
        case "tool":
            return _tool_entry(event, full=False)
        case "usage":
            return ActivityEntry(time=event.time, kind="usage", text=event.text, data=data)
        case "steered":
            kept = {key: data[key] for key in ("steering", "error", "code") if key in data}
            return ActivityEntry(time=event.time, kind="steered", text=event.text, origin=data.get("origin"), data=kept)
        case "finished":
            report = directory / "report.md"
            ended = {"status": data.get("status"), "report": str(report) if report.is_file() else None}
            return ActivityEntry(time=event.time, kind="ended", text=event.text, data=ended)
        case "failed":
            ended = {"code": data.get("code"), "remedy": data.get("remedy")}
            return ActivityEntry(time=event.time, kind="ended", text=event.text, data=ended)


def _tool_entry(event: CheckEvent, full: bool) -> ActivityEntry:
    data = event.data
    if data.get("phase") == "result":
        kind, kept = "tool-result", ("tool_call_id", "success")
    else:
        kind, kept = "tool", ("tool_call_id", "tool_name", "agent_id")
    if full:
        kept = (*kept, *FULL_FIELDS)
    return ActivityEntry(
        time=event.time, kind=kind, text=event.text, data={key: data[key] for key in kept if key in data}
    )
