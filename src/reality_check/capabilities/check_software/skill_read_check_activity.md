`read-check-activity` reads a check, running or ended, from any process: its state and its events,
in the same short form `check-software` prints. Each event's `id` is its line in the check's
`events.jsonl`. Read it again with `--after-event` and the last `id` you got for only what came
since. `--no-truncate` returns events whole, with a tool's arguments and result.

```bash
reality-check read-check-activity --check-id 20261013-142501-3f9a1c
reality-check read-check-activity --check-id 20261013-142501-3f9a1c --after-event 48
reality-check read-check-activity --check-id 20261013-142501-3f9a1c --after-event 63 --before-event 65 --no-truncate
```

```python
from reality_check.lib import read_check_activity

activity = read_check_activity("20261013-142501-3f9a1c", after_event=48)
activity.state, [(event.id, event.kind) for event in activity.events]
```

## Arguments

- `--check-id CHECK_ID`: the check, from its `started` event. Required.
- `--after-event N`: only events with an `id` larger than N. Past the check's last event it fails
  with `event-not-found`; read from the start again.
- `--before-event N`: only events with an `id` smaller than N.
- `--tail-events N`: of those, only the last N; `0` for none, to read only the state.
- `--no-truncate`: the events as `events.jsonl` keeps them, nothing left out or cut.
- `--checks-directory PATH`: where the check is kept, default `.agents/reality-check`.
- Library: `read_check_activity(check_id, after_event=None, before_event=None, tail_events=None, truncate=True,
  checks_directory=Path(".agents/reality-check"))`.

## Result

One line of JSON with:

- `check`: the check's `check.json`, such as its request, model, `origin`, `pid`, `last_event`,
  `timeout_seconds`, and `usage` so far.
- `state`: `running`, `done`, `cancelled`, `timed-out`, `failed`, or `crashed`, a check whose process is gone
  before it ended. A crashed check is resumed with `check-software --resume CHECK_ID`.
- `process_log`: what a detached check's process printed, when there is one; read it after a crash.
- `events`: in order, each with `id`, `check_id`, `time`, `kind`, `text`, and `data`, as
  `check-software` prints them. `usage` events are left out; `check.usage` sums them. A tool result
  is a `tool` event with `data.phase` `result` and the call's `data.tool_call_id`.
