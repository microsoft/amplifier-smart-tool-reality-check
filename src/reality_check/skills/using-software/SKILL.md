---
name: using-software
description: >-
  See and use software as a real user does while checking it: a browser that is already open and
  signed in, a browser in a universe, Playwright, computer use, a terminal for a CLI, or a tester
  for a native or mobile app. Use when choosing how to drive the app and see what a user sees.
---

Do what the user would do, through what the user would see. Reading the code or calling the API
directly is not using the app; do it only to explain what you saw.

## Pick the view

- Web app, and a browser the caller already uses: attach to it rather than starting a new one,
  so their sign-in is kept. A Chromium browser started with `--remote-debugging-port=9222` is
  reachable over CDP (`http://<host>:9222/json/version`); Playwright attaches with
  `chromium.connect_over_cdp(url)`. A browser extension or bridge the caller named is another way.
- Web app, nothing open: Playwright or a headless browser on this machine, or a browser in a
  universe next to the app.
- Desktop and native apps: computer use through cua-driver, with the using-computer-use skill.
  Use it when nothing else reaches the app, and also when what does reach it would not show what
  a user experiences. If it is not enabled, say so instead of guessing. For example:
  - An Electron or other desktop app built on web content: Playwright against its dev server
    misses the native window, menus, file dialogs, and tray.
  - A UI test hook or API that sets state directly: it passes where a user's clicks would not.
  - Canvas, game, or custom-drawn UIs: the DOM or tree says nothing about what is drawn.
  - OS-level steps a user goes through: file pickers, permission and sign-in prompts, installers,
    notifications.
- CLI: run it in a terminal as the user would, with their kind of shell and working directory,
  in a universe when it must not touch this machine (`digital-twin-universe exec`).
- Native or mobile: the platform's tester or simulator (Xcode `simctl`, Android `adb` and an
  emulator, WinAppDriver), only when installed. A missing one is something that seems off.

## Work like a user

- Follow the steps in order and note each one: what you did and what the app showed.
- Wait for what a user waits for: the page settled, the spinner gone, the message shown. Do not
  sleep blindly; wait on what you can see.
- Sign-in: enter a password or code that was made for this check yourself. A sign-in that belongs
  to the caller is theirs: use a browser where they are signed in, or open the sign-in page and
  stop to ask.
- Look past the happy path: slow responses, repeated requests, layout shifts, wording and spacing
  that differ between pages, and what happens with realistic data or a throttled network.
- Do not change the app to make a step pass. A failure is a finding.
