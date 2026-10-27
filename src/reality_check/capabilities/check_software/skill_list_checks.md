`list-checks` lists every check on this machine, running or ended, newest first. Each check is kept
in the project it was started from, and starting a check records that project, so the list covers
every project without knowing where each keeps its checks. Use it to find an earlier check without
its ID, then read it with `read-check`.

```bash
reality-check list-checks
reality-check list-checks --checks-directory .agents/reality-check
```

```python
from reality_check.lib import list_checks

latest = list_checks()[0]
latest.check_id, latest.state, latest.project.checks_directory
```

## Arguments

- `--checks-directory PATH`: only the checks kept here. Left out, every project's checks.
- Library: `list_checks(checks_directory=None)`.

## Result

A JSON list, newest first, each with:

- `check_id`, `request`, `target`, `started_at`, `ended_at`, `agent_provider`, `model`, and `origin`.
- `project`: `root`, the directory the check was started from, and `checks_directory`, where it is
  kept. Pass that as `--checks-directory` to the other commands.
- `state`: `running`, `done`, `cancelled`, `timed-out`, `failed`, or `crashed`. A state says how the
  check ran, not what it found: a `done` check can report failures.
- `resume`: the check this one continues, when it does.
- `has_report`: whether the check has written its report.

The projects are kept in `~/.agents/reality-check/projects.json`. A project whose directory is gone
is left out.
