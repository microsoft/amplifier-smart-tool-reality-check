---
name: using-browser
description: >-
  Drive a web app's real UI in a headless browser through the agent-browser CLI: open pages, read
  them, click and type, and screenshot them. Use for any software with a web UI.
---

`agent-browser` drives a headless browser. Use it for every web UI rather than `curl` or reading
the HTML.

Before the first command, learn it from the CLI itself; it describes the version installed:

    agent-browser skills list
    agent-browser skills get core
    agent-browser skills get dogfood     # for exploratory checks

- Pass the session from your prompt on every command: `--session <session>`. For a second
  browser, such as another user's, use `--session <session>-<role>`. Flows that run in parallel,
  in scripts or sub-agents, each take their own, such as `--session <session>-2`, so their pages
  and cookies do not clash.
- Each session is a browser of its own, with about 0.5 GB of memory and 250 processes and
  threads. Before running three or more at once, check the machine has room for them, and close
  each when its flow ends: `agent-browser --session <session> close`.
- Save screenshots into the evidence folder by path.
- This machine's trusted certificates are already handed to the browser. Do not turn off HTTPS
  checks.
