`cancel-check` cancels a check that is running, from any process. The cancel is written to the
check's directory, and the process running the check stops its agent within about a second.
The check's last event, `finished` with status `cancelled`, shows when it has stopped. Its
session can still be resumed.

```bash
reality-check cancel-check --check-id 20261013-142501-3f9a1c
```

```python
from reality_check.lib import cancel_check

cancel_check("20261013-142501-3f9a1c")
```

## Arguments

- `--check-id CHECK_ID`: the check, from its `started` event. Required.
- `--checks-directory PATH`: where the check is kept, default `.agents/reality-check`.
- Library: `cancel_check(check_id, checks_directory=Path(".agents/reality-check"))`.

## Result

Prints nothing and exits 0 once the cancel is written.
A check whose process is gone, `crashed`, refuses with `check-crashed`; resume it with
`check-software --resume CHECK_ID` instead.
