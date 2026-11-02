`read-check-activity` reads a check, running or ended: its state and its events.
Each event's `id` is its line in the check's `events.jsonl`.

A check can have hundreds of events, so read only what you need:

```bash
# first, or when you have lost track: the state and the latest events
reality-check read-check-activity --check-id 20261013-142501-3f9a1c --tail-events 3
# then, again until it ends: only what came since the last id you read; add --tail-events when much may have come
reality-check read-check-activity --check-id 20261013-142501-3f9a1c --after-event 48
# looking back: the latest events before an id
reality-check read-check-activity --check-id 20261013-142501-3f9a1c --before-event 48 --tail-events 3
# one event whole, with a tool's arguments and result
reality-check read-check-activity --check-id 20261013-142501-3f9a1c --after-event 63 --before-event 65 --no-truncate
```

When `state` is no longer `running`, read the last event with `--tail-events 1`.
It is `finished` when the check ended, with the result in `data`: its whole report and `next`.
It is `failed` when the check could not end, with `code`, `message`, and `remedy` in `data`.
When `state` is `crashed`, the process died before writing either: read `process_log` when there is one, then resume it with `check-software --resume`.

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
- `events`: in order, as `check-software` prints them, without `usage` events; `check.usage` sums them.
