`read-check-activity` reads a check, running or ended, from any process: its state and what its
agent was asked, said, thought, and did, as entries. Read it again with the cursor it returns to get
only what came since. A tool entry is shortened; `--tool-call-id` returns that call and its result in
full.

```bash
reality-check read-check-activity --check-id 20261013-142501-3f9a1c
reality-check read-check-activity --check-id 20261013-142501-3f9a1c --after 48213
reality-check read-check-activity --check-id 20261013-142501-3f9a1c --tool-call-id toolu_01AbC
```

```python
from reality_check.lib import read_check_activity

activity = read_check_activity("20261013-142501-3f9a1c")
activity.state, [entry.kind for entry in activity.entries], activity.cursor
```

## Arguments

- `--check-id CHECK_ID`: the check, from its `started` event. Required.
- `--after N`: the `cursor` of an earlier read; only what came after it.
- `--tool-call-id ID`: only that tool call and its result, with `arguments`, `result`, and
  `detailed_result` in `data`. Take it from a `tool` entry's `data.tool_call_id`.
- `--checks-directory PATH`: where the check is kept, default `.agents/reality-check`.
- Library: `read_check_activity(check_id, after=None, tool_call_id=None, checks_directory=Path(".agents/reality-check"))`.

## Result

JSON with:

- `check`: the check's `check.json`, such as its request, model, `origin`, `pid`, and `last_event`.
- `state`: `running`, `done`, `cancelled`, `failed`, or `crashed`, a check whose process is gone
  before it ended. A crashed check is resumed with `check-software --resume CHECK_ID`.
- `process_log`: what a detached check's process printed, when there is one; read it after a crash.
- `entries`: each with `time`, `kind`, `text`, `origin` (for `request` and `steered`), and `data`.
  The kinds: `request`, `said`, `reasoning`, `tool`, `tool-result`, `usage`, `steered`, and
  `ended`, whose `data` has the `status` and `report` path, or the failure's `code` and `remedy`.
- `cursor`: pass it as `--after` to read on.
