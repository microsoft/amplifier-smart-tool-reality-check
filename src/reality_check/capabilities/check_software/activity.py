"""A check's activity: its events in the short form the CLI prints, or whole, picked by their ids."""

from pathlib import Path

from reality_check.capabilities.check_software.record import EVENTS, PROCESS_LOG, check_state, load_record, read_events
from reality_check.schemas import DEFAULT_CHECKS_DIRECTORY, CheckActivity, RealityCheckError, brief


def read_check_activity(
    check_id: str,
    after_event: int | None = None,
    before_event: int | None = None,
    tail_events: int | None = None,
    truncate: bool = True,
    checks_directory: Path = DEFAULT_CHECKS_DIRECTORY,
) -> CheckActivity:
    """The check as it stands and its events, from any process, each with its id, its line in events.jsonl.

    Args:
        check_id: The check, running or ended.
        after_event: Only events with a larger id; past the check's last event it raises `event-not-found`.
        before_event: Only events with a smaller id.
        tail_events: Of those, only the last this many; 0 for none.
        truncate: False for the events as events.jsonl keeps them, rather than in the short form the CLI prints.
        checks_directory: Where the check is kept.
    """
    for name, value in (("after_event", after_event), ("before_event", before_event), ("tail_events", tail_events)):
        if value is not None and value < 0:
            raise RealityCheckError(
                code="bad-event-selection",
                message=f"{name} is {value}, and it cannot be negative.",
                remedy="Pass 0 or more, or leave it out.",
            )
    root = checks_directory.resolve()
    record = load_record(root, check_id)
    directory = root / check_id
    events, _ = read_events(directory / EVENTS)
    last = events[-1].id if events else 0
    if after_event is not None and after_event > last:
        raise RealityCheckError(
            code="event-not-found",
            message=f"Check {check_id} has no event {after_event}; its last is {last}.",
            remedy="Pass an id an earlier read returned, or read without after_event from the first event.",
        )
    picked = [
        short
        for event in events
        if (after_event is None or event.id > after_event) and (before_event is None or event.id < before_event)
        if (short := brief(event, truncate)) is not None
    ]
    if tail_events is not None:
        picked = picked[-tail_events:] if tail_events else []
    log = directory / PROCESS_LOG
    return CheckActivity(
        check=record,
        state=check_state(record),
        process_log=log if log.is_file() else None,
        events=picked,
    )
