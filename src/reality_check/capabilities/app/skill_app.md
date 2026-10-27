`app` serves the Reality Check app in a browser page on this machine, prints its URL, and keeps
serving until interrupted. Only this machine can reach it.

The app shows every check on this machine, from every project checks were started from, newest
first and grouped by project. A running check shows how long it has run and what its agent is
doing as it happens. Each check opens on its report, with links to its evidence that open in
place: screenshots, requests, console logs, and other files, with those the report does not cite
listed apart. Beside it are what the check's agent was asked, said, and did, and the check's
details: its request, agent provider, model, timings, usage, and how it ran, which is not what it
found. A check's menu copies its ID or folder path and, on a machine with a file manager,
opens its folder there: Explorer on Windows and under WSL, Finder on macOS, or what `xdg-open`
picks on Linux.

Reports with the standard section headings keep the summary, Needs attention, and Next steps
open, with observations, coverage, and run details expandable. Embedded screenshots open in the
evidence viewer. Older reports remain readable as ordinary Markdown, and Source shows the
original report text.

The app only shows checks. The person's agent starts, steers, and cancels them with the tool.

The app's view is an MCP App. The page hosts it the way an MCP Apps host would inline, for agents
that cannot. `mcp`'s `open_app` tool serves the same app from inside a session.

```bash
# every check on this machine, on a free port; prints the URL, then blocks until Ctrl+C
reality-check app

# also the checks kept in another directory, opened on the newest of them, on a fixed port
reality-check app --directory checks --port 8788
```

```python
from reality_check.lib import app_server, app_view

app = app_server()
app.open().url  # the browser host page, which reaches app.server at its own /mcp
app.close()
app_view()  # the view's HTML, the MCP App resource
```

`open` returns once the page is listening, so the URL answers at once, and serves from daemon
threads until `close` or the process exits.

## Arguments

- `--port N`: the port to bind on `127.0.0.1`. A free one is chosen when omitted.
- `--directory DIR`: a checks directory to add to the projects the app shows, and to open on its
  newest check.

## Result

The URL on stdout, `http://127.0.0.1:<port>`, then nothing more while it serves. Uvicorn writes
only warnings and errors to stderr.
