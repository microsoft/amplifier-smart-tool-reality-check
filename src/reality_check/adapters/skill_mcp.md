`mcp` runs the tool's MCP server over stdio, with the app as an [MCP App](https://github.com/modelcontextprotocol/ext-apps).

Register it only in a host that renders MCP Apps. Such a host shows the app's view itself, where
and when it decides: in the chat, in a panel or tab, or in a window of its own. In any other host,
`open_app` only returns the URL that `reality-check app` prints, so show checks with `app` there
instead.

The host owns the process. Do not run it yourself in a terminal: it waits for an MCP client on
stdin. Nothing is served until `open_app` is called, so each session gets its own app on its own
free port, and a session that never opens it binds nothing.

The library has no `mcp` function. The command calls `run_stdio()` in `reality_check.adapters.mcp`,
which serves `app_server().server` from the library over stdio.

## Register it in your host

Register the command `reality-check` with the single argument `mcp`, through the host's own way of
adding MCP servers and in its own config format. In the common JSON form:

```json
{ "mcpServers": { "reality-check": { "command": "reality-check", "args": ["mcp"] } } }
```

The host launches the server, so `reality-check` must be on the PATH of the machine the host runs
on. Reload the host's MCP servers after registering: a running session may not load new ones until
then. It is registered once `open_app` is among your tools. Change only the config of the host you
run in.

Before registering in one of these hosts, read its file:

- Codex Desktop: `adapters/hosts/codex-desktop.md`
- Amplifier Unified, where `app_control` has `smartTools.*` actions: `adapters/hosts/amplifier-unified.md`

## Arguments

- `--directory DIR`: a checks directory to add to the projects the app shows, and to open on its
  newest check.

## Tools

- `open_app`, with an optional `check_id` and `checks_directory`: serves the app and returns its
  browser URL, and the check it opens on. Its `_meta.ui.resourceUri` names the view, so a host
  that renders MCP Apps shows it. Call it with the check's ID after starting a check.
  Without `checks_directory`, the check is found in every project. Calling it again returns the
  same URL.
- `list_checks`, `read_check`, and `read_check_activity`: the library's, which the view polls and
  calls. They read only the checks directories of registered projects. `list_checks` also says
  whether the machine can show a folder in a file manager.
- `open_check_folder`: shows a check's folder in the file manager of the machine the server runs
  on, for the view's menu.

All but `open_app` are listed only to hosts that render MCP Apps, with `visibility: ["app"]`, so
no model sees them. None of them starts, steers, or cancels a check.

## Resources

- `ui://reality-check/app`: the view.
- `reality-check://checks/{checks_directory}/{check_id}/{+path}`: a file from a check's evidence
  folder, as a base64 blob, with the checks directory percent-encoded. HTML and SVG come as
  `text/plain`. Nothing else in a check's directory can be read.
