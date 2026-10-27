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

Everything goes in the evidence directory you were given, or else one you create for the check,
flat, named so it sorts in step order:

```
01-open-home.png
02-click-send.png
02-click-send.har
02-click-send.console.log
03-export.terminal.txt
timings.json
```

Use `<step>-<what>.<ext>`, with the step number from the report. In the report, give each file's
path relative to where the report is saved, such as `evidence/01-open-home.png`, so its links
work wherever the report is read.

## What to record, by kind

- Web: a screenshot after each step that matters (full page when layout matters); the network
  log as HAR or a list of method, URL, status, size, time, and for a redirect its `Location`
  header (HAR keeps it); the console messages and page
  errors; timings such as time to first content and to the page being usable. Playwright records
  HAR with `record_har_path` and the console with `page.on("console")`; CDP gives the same.
- CLI: the exact command, its stdout, stderr, and exit code, in one transcript per step; the
  files it wrote when they matter.
- Terminal UIs, such as editors: run the app in tmux with a UTF-8 locale. After each step that
  matters, keep the screen from `tmux capture-pane -p -e`, the cursor from
  `tmux display-message -p '#{cursor_x},#{cursor_y}'`, and the position the app shows, such as a
  status bar's line and column. An image of the screen must show what the user sees: the cursor,
  and real glyphs for wide characters and emoji. Take it from a real terminal emulator, such as
  xterm under Xvfb with CJK and emoji fonts, not from a re-render that drops them.
- Desktop and mobile: a screenshot or a short screen recording per step, and the app's logs
  (`adb logcat`, `xcrun simctl spawn booted log`, the app's own log file). With computer use,
  the screenshots are `get_window_state`'s `screenshot_out_file`, before and after each checked
  action, and `verify_state` output where the app has an accessibility tree.
- Services: the log lines from the time of the failure, from the app or its universe.

## What makes it evidence

- It was captured while you did the step, not reconstructed afterwards. Start recording before
  the first action that can fail.
- A failure's record shows the moment it happened: the request that returned 500, the console
  error, the screenshot of the wrong state. When a page fails to load, record its URL and the
  error; the browser's error page often screenshots blank.
- It can show what it is cited for. A screen image that does not draw the cursor is no evidence of
  where the cursor is; cite a record that does.
- It is kept as captured: do not merge, rename, or delete evidence files afterwards.
- Large responses, repeated polling, and slow requests are findings too; keep the record that
  shows them.
- Never put secrets in evidence: blur or omit tokens, passwords, and cookies.
