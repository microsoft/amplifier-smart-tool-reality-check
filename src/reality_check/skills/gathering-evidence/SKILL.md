---
name: gathering-evidence
description: >-
  Decide what evidence to record while checking software, for web, CLI, desktop, and mobile
  apps, and how to name and store it so a report can point at it. Use before and during any
  check whose verdicts must stand on what was recorded rather than on what was claimed.
---

A verdict stands on what was recorded. Each item in the report names the files it rests on. An
item you could not record is "not checked", never a pass.

## Where it goes

Everything goes in a directory you choose, such as one you create for the check, flat, named so it
sorts in step order:

```
01-open-home.png
02-click-send.png
02-click-send.har
02-click-send.console.log
03-export.terminal.txt
timings.json
```

Use `<step>-<what>.<ext>`, with the step number from the report. Give every file's path in your
final message.

## What to record, by kind

- Web: a screenshot after each step that matters (full page when layout matters); the network
  log as HAR or a list of method, URL, status, size, and time; the console messages and page
  errors; timings such as time to first content and to the page being usable. Playwright records
  HAR with `record_har_path` and the console with `page.on("console")`; CDP gives the same.
- CLI: the exact command, its stdout, stderr, and exit code, in one transcript per step; the
  files it wrote when they matter.
- Desktop and mobile: a screenshot or a short screen recording per step, and the app's logs
  (`adb logcat`, `xcrun simctl spawn booted log`, the app's own log file).
- Services: the log lines from the time of the failure, from the app or its universe.

## What makes it evidence

- It was captured while you did the step, not reconstructed afterwards.
- A failure's record shows the moment it happened: the request that returned 500, the console
  error, the screenshot of the wrong state.
- Large responses, repeated polling, and slow requests are findings too; keep the record that
  shows them.
- Never put secrets in evidence: blur or omit tokens, passwords, and cookies.
