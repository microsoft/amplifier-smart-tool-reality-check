Codex Desktop, the Codex app, renders MCP Apps inline in the chat. The Codex CLI and `codex exec`
do not, so show checks there with `reality-check app`. If you cannot tell which one you run in, ask
the user.

Register the server with Codex's own command. It writes the server to `$CODEX_HOME/config.toml`,
which is `~/.codex/config.toml` by default:

```bash
codex mcp add reality-check -- reality-check mcp
codex mcp get reality-check
```

Without the `codex` command, add the same entry to that file by hand:

```toml
[mcp_servers.reality-check]
command = "reality-check"
args = ["mcp"]
```

A new thread loads the server; a running one may not. Tell the user to start a new thread, where
Codex Desktop shows the check in the chat after `open_app`.
