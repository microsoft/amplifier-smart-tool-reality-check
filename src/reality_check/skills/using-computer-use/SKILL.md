---
name: using-computer-use
description: >-
  Drive any app's real UI on the desktop through the cua-driver CLI: see it in screenshots, read it
  through its accessibility tree when it has one, click and type. Use for desktop and native apps,
  and for anything with no better option that is also realistic enough to validate effectively.
---

Once you have deemed it appropriate to use computer input, follow the guidelines below.
Computer use is slow and may take focus from the user, so prefer using other methods when possible.

## Calling it

- `cua-driver call <tool>` with the JSON arguments on stdin; the result is JSON.
  `cua-driver list-tools` lists the tools and `cua-driver describe <tool>` gives a tool's arguments.
- Start with `start_session` and pass the same `session` label on every call, then `end_session`
  at the end. Element tokens from one session are refused in another (`stale_element_token`).
- The daemon is already running; never run `serve`, `stop`, or `update`.

## Seeing the app

Two ways, both first class. Every app works with the first.

- Screenshots: `get_window_state` with `screenshot_out_file` writes a PNG; open it with your file
  viewing tool to see it. Act on window-local pixels from that screenshot (`click`, `double_click`,
  `scroll`, `drag`), with its `capture_id` so stale coordinates are refused. For a small target,
  `zoom` then click with `from_zoom: true`. Take a new screenshot before each pixel click; a
  coordinate from an older one can hit the wrong control.
- Accessibility tree, when the app has one: element tokens, values, and `verify_state`. It is
  faster, works in the background, and gives exact text. Tokens are valid only for the snapshot
  that made them. Canvas, game, Flutter, and custom-drawn apps often have none or a thin one; that
  is normal, not a reason to stop.

## The loop

`launch_app`, then `get_window_state`, then look (the screenshot always, the tree when there is
one), act, and look again to confirm the effect. A click reports no effect by itself. A verdict
rests on what was seen after the action: a `verify_state` result, a value in the tree, or a
screenshot that shows it.

- Background input first. Use `delivery_mode: "foreground"` only when background input has no
  effect or returns `background_unavailable`, and say in the report that it took focus.
- `verify_state` matches only actionable elements; read static labels from `get_window_state`. A
  `degraded` tree or an `untrusted_source` result cannot be trusted alone; confirm with a fresh
  screenshot.
- Electron and web content inside an app: list selection and typing need foreground delivery,
  and field text is not in the tree, so read it from the screenshot.
- Under WSL the driver is a Windows program: give it Windows paths (`wslpath -w <path>`).

## Evidence

Write every `screenshot_out_file` into the evidence directory the prompt names, one before
and one after each checked action, named by step. Keep the `verify_state` output when there is a tree.

## Gotchas

- On Windows, `launch_app` for a Store (UWP) app returns the pid of `ApplicationFrameHost`, which
  other apps share. Close such an app through its window's Close button, never `kill_app`.
- Elevated apps refuse input from a non-elevated driver.
- When the daemon is gone or every call fails, stop using computer use, say so in the report, and
  mark the affected items "not checked" with the error. When one control fails while others work,
  try the other ways in, in order: a background click on its element, a foreground pixel click from
  a fresh screenshot of the app's main window, then the keyboard. Name each way tried in the report.
- Close the apps you launched before ending, so nothing is left open on the user's desktop.
- The user might be interacting with their desktop, so if unexpected things happen that might also be the cause.