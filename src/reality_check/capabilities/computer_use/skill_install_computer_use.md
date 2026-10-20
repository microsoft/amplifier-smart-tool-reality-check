`install-computer-use` installs cua-driver 0.36.0, the CLI a check's agent uses to drive desktop
apps: it sees them in screenshots and their accessibility tree, and clicks and types. Run it once per
machine, after installing reality-check. It needs no model provider. Each download is checked
against its pinned SHA-256 and unpacked into reality-check's own folder; it changes no PATH, shell
profile, or startup task, and cua-driver's telemetry and update checks stay off.

An existing cua-driver 0.36.0 on PATH or from cua-driver's own installer is used as it is. Running
it again reports the install that is there.

Under WSL it installs the Windows build into the Windows user's LocalAppData, because checks drive
the Windows desktop. On Linux it needs a desktop session (DISPLAY or WAYLAND_DISPLAY). On macOS it
installs `CuaDriver.app` into `/Applications`, and the user grants Accessibility and Screen Recording
by hand once.

Checks find the install themselves. A check that needs computer use before it is installed has
its agent run this command and goes on with it.

```bash
reality-check install-computer-use
```

```python
from reality_check.lib import install_computer_use

install = install_computer_use()
install.executable, install.remaining_step
```

## Arguments

None.

## Result

JSON with `target` (`windows`, `wsl`, `linux`, or `macos`: the desktop checks drive), `version`,
`executable` (the cua-driver checks run), `already_installed` (true when nothing was downloaded),
and `remaining_step` (what the user still does by hand, or null).

Under WSL:

```json
{
  "target": "wsl",
  "version": "0.36.0",
  "executable": "/mnt/c/Users/ada/AppData/Local/reality-check/cua-driver/0.36.0/cua-driver.exe",
  "already_installed": false,
  "remaining_step": null
}
```

On macOS:

```json
{
  "target": "macos",
  "version": "0.36.0",
  "executable": "/Applications/CuaDriver.app/Contents/MacOS/cua-driver",
  "already_installed": false,
  "remaining_step": "Once, unless already done: run `/Applications/CuaDriver.app/Contents/MacOS/cua-driver permissions grant` and allow Accessibility and Screen Recording for CuaDriver."
}
```

Failures name their fix: `computer-use-unsupported` (no desktop, or an OS or architecture cua-driver
has no build for), `computer-use-download-failed`, `computer-use-download-corrupt` (the hash does
not match; nothing is installed), `computer-use-install-failed` (the folder is not writable), and
`computer-use-install-broken` (the install folder is there but does not run).
