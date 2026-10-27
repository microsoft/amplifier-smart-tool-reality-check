`mcp` runs the tool's MCP server over stdio, with the app as an [MCP App](https://github.com/modelcontextprotocol/ext-apps).

Configure the client to launch the command `reality-check` with the single argument `mcp`. The
client owns the process. Do not run it yourself in a terminal: it waits for an MCP client on
stdin. Nothing is served until `open_app` is called, so each session gets its own app on its own
free port, and a session that never opens it binds nothing.

```json
{ "mcpServers": { "reality-check": { "command": "reality-check", "args": ["mcp"] } } }
```

The library has no `mcp` function. The command calls `run_stdio()` in `reality_check.adapters.mcp`,
which serves `app_server().server` from the library over stdio.

## Arguments

- `--directory DIR`: a checks directory to add to the projects the app shows, and to open on its
  newest check.

## Tools

- `open_app`, with an optional `check_id` and `checks_directory`: serves the app and returns its
  browser URL, and the check it opens on. Its `_meta.ui.resourceUri` names the view, so a host
  that renders MCP Apps shows it inline. Call it with the check's ID after starting a check.
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
