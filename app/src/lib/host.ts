import {
  App,
  type McpUiDisplayMode,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps";

import type { OpenedApp } from "@/lib/api";
import { setHostTheme } from "@/lib/theme";
import { QuietPostMessageTransport } from "@/lib/transport";

export const app = new App(
  { name: "Reality Check", version: "1.0.0" },
  { availableDisplayModes: ["inline", "fullscreen"] },
);

type Display = { mode: McpUiDisplayMode; available: McpUiDisplayMode[] };

const displayListeners = new Set<(display: Display) => void>();
const openedListeners = new Set<(opened: OpenedApp) => void>();
let display: Display = { mode: "inline", available: [] };
let lastOpened: OpenedApp | null = null;

/** Calls `listener` with how the host shows the view now and which modes it offers, then each time that changes. */
export function onDisplay(listener: (display: Display) => void): () => void {
  listener(display);
  displayListeners.add(listener);
  return () => {
    displayListeners.delete(listener);
  };
}

/** Ask the host to show the view another way, such as fullscreen; it may refuse, and says which it chose. */
export async function requestDisplayMode(mode: McpUiDisplayMode) {
  await app.requestDisplayMode({ mode });
}

/** Calls `listener` with what `open_app` returned when a host renders the view for that call, now and later. */
export function onOpened(listener: (opened: OpenedApp) => void): () => void {
  if (lastOpened) {
    listener(lastOpened);
  }
  openedListeners.add(listener);
  return () => {
    openedListeners.delete(listener);
  };
}

/** Opens `url` in the person's browser through the host, since the view's frame cannot open windows itself. */
export function openLink(url: string) {
  void app.openLink({ url });
}

// Only the theme and display mode: the view keeps its own fonts and palette, so it looks the same in every host.
function applyHostContext(context: McpUiHostContext) {
  if (context.theme) {
    setHostTheme(context.theme);
  }
  if (context.displayMode || context.availableDisplayModes) {
    display = {
      mode: context.displayMode ?? display.mode,
      available: context.availableDisplayModes ?? display.available,
    };
    for (const listener of displayListeners) {
      listener(display);
    }
  }
}

app.addEventListener("hostcontextchanged", applyHostContext);
// Registered before connecting: the host sends the tool result once, right after the handshake.
app.addEventListener("toolresult", (result) => {
  const structured = result.structuredContent as OpenedApp | undefined;
  if (result.isError || !structured || !("focus" in structured)) {
    return;
  }
  lastOpened = structured;
  for (const listener of openedListeners) {
    listener(structured);
  }
});

export async function connect(): Promise<void> {
  if (window.parent === window) {
    throw new Error(
      "This page is an MCP App view and needs a host. Run `reality-check app`, or ask your agent to call `open_app`.",
    );
  }
  await app.connect(
    new QuietPostMessageTransport(window.parent, window.parent),
  );
  const context = app.getHostContext();
  if (context) {
    applyHostContext(context);
  }
}
