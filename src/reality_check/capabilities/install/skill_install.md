Run `reality-check install` once per machine, right after installing reality-check, with no
options: it installs every component this machine supports, which gives checks the most to work
with. `--component` only limits it to the ones named. It needs no model provider. Running it again
reports what is there.

It does not register the MCP server that shows checks in the host. In a host that renders MCP Apps,
`reality-check mcp --help` says how.

Checks find what is installed themselves. A check that needs a component before it is installed has
its agent install it and goes on with it.

## Components

`computer-use` installs cua-driver 0.36.0, the CLI a check's agent uses to drive desktop apps: it
sees them in screenshots and their accessibility tree, and clicks and types. Each download is
checked against its pinned SHA-256 and unpacked into reality-check's own folder; it changes no PATH,
shell profile, or startup task, and cua-driver's telemetry and update checks stay off. An existing
cua-driver 0.36.0 on PATH or from cua-driver's own installer is used as it is.

Under WSL it installs the Windows build into the Windows user's LocalAppData, because checks drive
the Windows desktop. On Linux it needs a desktop session (DISPLAY or WAYLAND_DISPLAY). On macOS it
installs `CuaDriver.app` into `/Applications`, and the user grants Accessibility and Screen Recording
by hand once.

`browser` installs agent-browser 0.41.1, the CLI a check's agent uses to drive web apps' UIs in a
headless Chrome or Chromium: pages, screenshots, console, and network. It downloads the release
binary and the skills from its npm package, each checked against its pinned hash, into
reality-check's own folder; it changes no PATH, shell profile, or startup task, and agent-browser's
update check stays off. When no browser launches, it downloads Chrome for Testing into
`~/.agent-browser/browsers`. On Linux it also installs Chromium's system libraries through sudo when
sudo needs no password; otherwise the failure names the command that does. On Linux x64 that goes
through `sudo` even as root, so a root container without `sudo` installs it first, such as
`apt-get install -y sudo`. Alpine has no Chrome for Testing and needs the distribution's Chromium.
On Linux, without
`certutil`, `remaining_step` names the package that makes browsers trust this machine's
certificates.

```bash
reality-check install
reality-check install --component computer-use
reality-check install --component browser
```

```python
from reality_check.lib import install

result = install()
result.complete, [each.remaining_step for each in result.installed], result.not_installed
```

## Arguments

- `--component NAME`: only this component; repeatable. One of `computer-use` or `browser`. Every
  component when omitted.

## Result

JSON with `installed`, `not_installed`, and `complete`. Each entry in `installed` has `component`,
`version`, `executable`, `already_installed` (true when nothing was downloaded), and
`remaining_step` (what the user still does by hand, or null). A `computer-use` entry adds `target`
(`windows`, `wsl`, `linux`, or `macos`: the desktop checks drive), and its `executable` is the
cua-driver checks run. A `browser` entry's `executable` is agent-browser, and it adds
`skills_directory`, which agent-browser finds through `AGENT_BROWSER_SKILLS_DIR`. Each entry in
`not_installed` has `component`, `code`, `message`, `remedy`, and `unsupported` (true when this
machine cannot run it as it is, such as computer use with no desktop).

`complete` is true when everything asked for is installed; with no `--component`, when everything
this machine supports is. The command exits 1 when `complete` is false.

On Linux without a desktop:

```json
{
  "installed": [
    {
      "component": "browser",
      "version": "0.41.1",
      "executable": "/home/ada/.local/share/reality-check/agent-browser/0.41.1/bin/agent-browser",
      "skills_directory": "/home/ada/.local/share/reality-check/agent-browser/0.41.1/skill-data",
      "already_installed": true,
      "remaining_step": null
    }
  ],
  "not_installed": [
    {
      "component": "computer-use",
      "code": "computer-use-unsupported",
      "message": "Computer use cannot run here. There is no desktop: neither DISPLAY nor WAYLAND_DISPLAY is set.",
      "remedy": "Run in a desktop session, with DISPLAY or WAYLAND_DISPLAY set.",
      "unsupported": true
    }
  ],
  "complete": true
}
```

Under WSL:

```json
{
  "installed": [
    {
      "component": "computer-use",
      "target": "wsl",
      "version": "0.36.0",
      "executable": "/mnt/c/Users/ada/AppData/Local/reality-check/cua-driver/0.36.0/cua-driver.exe",
      "already_installed": false,
      "remaining_step": null
    },
    {
      "component": "browser",
      "version": "0.41.1",
      "executable": "/home/ada/.local/share/reality-check/agent-browser/0.41.1/bin/agent-browser",
      "skills_directory": "/home/ada/.local/share/reality-check/agent-browser/0.41.1/skill-data",
      "already_installed": false,
      "remaining_step": null
    }
  ],
  "not_installed": [],
  "complete": true
}
```

On macOS, `remaining_step` is "Once, unless already done: run
`/Applications/CuaDriver.app/Contents/MacOS/cua-driver permissions grant` and allow Accessibility
and Screen Recording for CuaDriver."

Codes name their fix: `computer-use-unsupported` (no desktop, or an OS or architecture cua-driver
has no build for), `computer-use-download-failed`, `computer-use-download-corrupt` (the hash does
not match; nothing is installed), `computer-use-install-failed` (the folder is not writable), and
`computer-use-install-broken` (the install folder is there but does not run). For `browser`:
`browser-unsupported`, `browser-download-failed` (including Chrome for Testing),
`browser-download-corrupt`, `browser-install-failed`, `browser-install-broken`,
`browser-no-browser` (musl Linux with no Chromium that launches),
`browser-missing-system-libraries`, `browser-daemon-failed` (agent-browser's daemon does not start),
`browser-socket-directory` (no private short folder for agent-browser's sockets), and
`browser-launch-failed`.
