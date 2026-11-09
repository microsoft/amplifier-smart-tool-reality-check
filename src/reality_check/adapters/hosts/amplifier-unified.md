Amplifier Unified renders MCP Apps in a Canvas tab beside the chat, and only when asked to. Its MCP
servers live in Amplifier Unified's own state, managed through `app_control`'s `smartTools.*`
actions, with no config file to edit. Its own Smart Tools guidance has the details of each action.

1. `smartTools.configure` a server named `reality-check` with the `stdio` transport, the command
   `reality-check`, and the arguments `["mcp"]`. Then `smartTools.connect` it: configuring does not
   connect. It is registered once `/smartTools` shows it connected.
2. Call `open_app` through `smartTools.discover`, `smartTools.schemas`, and `smartTools.call`.
3. Once the call completes, `smartTools.open` with the server's ID, the tool `open_app`, and the
   call's `operationId`. The view then opens in a Canvas tab. The user can also open it with "Open
   interactive view".

Amplifier Unified offers the view only the `inline` display mode, not `fullscreen` or `pip`. If
links in the view do not open, give the user the URL `open_app` returned, which opens the same app
in a browser.
