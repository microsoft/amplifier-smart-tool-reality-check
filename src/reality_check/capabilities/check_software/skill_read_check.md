`read-check` reads a check as it stands, running or ended: its record, its report, and the evidence
files it has saved so far. The report comes back with every path into the check's evidence folder,
absolute or relative to wherever the check ran, written as `evidence/<name>`, so its links work
from the check's directory. `report.md` on disk is left as written.

```bash
reality-check read-check --check-id 20261013-142501-3f9a1c
```

```python
from reality_check.lib import read_check

check = read_check("20261013-142501-3f9a1c")
check.state, check.report, [file.path for file in check.evidence if not file.referenced]
```

## Arguments

- `--check-id CHECK_ID`: the check, from `list-checks` or its `started` event. Required.
- `--checks-directory PATH`: where the check is kept, default `.agents/reality-check`.
- Library: `read_check(check_id, checks_directory=Path(".agents/reality-check"))`.

## Result

JSON with:

- `check`: the check's `check.json`, such as its request, model, `origin`, `timeout_seconds`, and
  `usage`.
- `state`: how the check ran, as `list-checks` gives it. Only the report says what passed.
- `project` and `directory`: where the check was started from and where it is kept.
- `report`: the report in Markdown, or null until the check writes one.
- `evidence`: each file with `path`, relative to `directory`, `media_type`, `size`, `modified_at`,
  and `referenced`, whether the report cites it.
- `resumes` and `previous_checks`: the checks this one continues or builds on, each a `check_id`
  and the `checks_directory` it is kept in.
