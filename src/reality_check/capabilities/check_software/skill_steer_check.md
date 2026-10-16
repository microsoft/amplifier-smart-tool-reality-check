`steer-check` sends a message to the agent of a check that is running, from any process. The
message is written to the check's directory, and the process running the check delivers it
within about a second; a `steered` event in that check's output shows when it landed.

```bash
reality-check steer-check --check-id 20261013-142501-3f9a1c --message "Skip the settings pages"
```

```python
from reality_check.lib import steer_check

steer_check("20261013-142501-3f9a1c", "Skip the settings pages")
```

## Arguments

- `--check-id CHECK_ID`: the check, from its `started` event. Required.
- `--message TEXT`: what to tell the agent. Required.
- `--checks-directory PATH`: where the check is kept, default `.agents/reality-check`.
- Library: `steer_check(check_id, message, checks_directory=Path(".agents/reality-check"))`.

## Result

Prints nothing and exits 0 once the message is written.
