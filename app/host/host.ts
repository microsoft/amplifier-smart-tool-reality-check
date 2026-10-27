import {
  AppBridge,
  RESOURCE_MIME_TYPE,
  buildAllowAttribute,
  type McpUiResourcePermissions,
  type McpUiSandboxProxyReadyNotification,
  type McpUiTheme,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import { EXTENSION_ID } from "@modelcontextprotocol/ext-apps/server";
import {
  Client,
  StreamableHTTPClientTransport,
} from "@modelcontextprotocol/client";

import { QuietPostMessageTransport } from "../src/lib/transport";

const HOST = { name: "Reality Check browser host", version: "1.0.0" };
const VIEW_URI = "ui://reality-check/app";
const SANDBOX_ATTRIBUTE = "allow-scripts allow-same-origin allow-forms";
const PROXY_READY: McpUiSandboxProxyReadyNotification["method"] =
  "ui/notifications/sandbox-proxy-ready";

const darkScheme = window.matchMedia("(prefers-color-scheme: dark)");
const theme = (): McpUiTheme => (darkScheme.matches ? "dark" : "light");
const containerDimensions = () => ({
  width: window.innerWidth,
  height: window.innerHeight,
});

function sandboxUrl(): URL {
  const port = document
    .querySelector<HTMLMetaElement>('meta[name="reality-check-sandbox-port"]')
    ?.content.trim();
  if (!port || !/^\d+$/.test(port)) {
    throw new Error(
      "This page was not served by `reality-check app`, so it has no sandbox to load the view in.",
    );
  }
  // Same hostname as this page, other port: a different origin, as the MCP Apps spec requires of a web host.
  return new URL(
    `${location.protocol}//${location.hostname}:${port}/sandbox.html`,
  );
}

async function readView(
  client: Client,
): Promise<{ html: string; permissions?: McpUiResourcePermissions }> {
  const { contents } = await client.readResource({ uri: VIEW_URI });
  const [content] = contents;
  if (contents.length !== 1 || content.mimeType !== RESOURCE_MIME_TYPE) {
    throw new Error(
      `${VIEW_URI} is not a single ${RESOURCE_MIME_TYPE} resource.`,
    );
  }
  const html = "blob" in content ? atob(content.blob) : content.text;
  const permissions = (
    content._meta?.ui as { permissions?: McpUiResourcePermissions } | undefined
  )?.permissions;
  return { html, permissions };
}

function loadSandbox(
  url: URL,
  permissions?: McpUiResourcePermissions,
): Promise<HTMLIFrameElement> {
  const iframe = document.createElement("iframe");
  iframe.title = "Reality Check";
  iframe.setAttribute("sandbox", SANDBOX_ATTRIBUTE);
  const allow = buildAllowAttribute(permissions);
  if (allow) {
    iframe.setAttribute("allow", allow);
  }
  const ready = new Promise<HTMLIFrameElement>((resolve) => {
    const listener = ({ source, data }: MessageEvent) => {
      if (source === iframe.contentWindow && data?.method === PROXY_READY) {
        window.removeEventListener("message", listener);
        resolve(iframe);
      }
    };
    window.addEventListener("message", listener);
  });
  iframe.src = url.href;
  document.body.append(iframe);
  return ready;
}

function createBridge(client: Client): AppBridge {
  const capabilities = client.getServerCapabilities();
  const bridge = new AppBridge(
    client,
    HOST,
    {
      openLinks: {},
      serverTools: capabilities?.tools,
      serverResources: capabilities?.resources,
    },
    {
      // No style variables, so the view keeps its own bundled font and palette.
      hostContext: {
        theme: theme(),
        platform: "web",
        displayMode: "fullscreen",
        availableDisplayModes: ["fullscreen"],
        containerDimensions: containerDimensions(),
      },
    },
  );
  bridge.onopenlink = async ({ url }) => {
    window.open(url, "_blank", "noopener,noreferrer");
    return {};
  };
  // The view fills the window and scrolls itself, so its reported size changes nothing here.
  bridge.onsizechange = () => {};
  darkScheme.addEventListener("change", () =>
    bridge.sendHostContextChange({ theme: theme() }),
  );
  window.addEventListener("resize", () =>
    bridge.sendHostContextChange({
      containerDimensions: containerDimensions(),
    }),
  );
  return bridge;
}

async function main(): Promise<void> {
  const client = new Client(HOST, {
    capabilities: {
      extensions: { [EXTENSION_ID]: { mimeTypes: [RESOURCE_MIME_TYPE] } },
    },
  });
  await client.connect(
    new StreamableHTTPClientTransport(new URL("/mcp", location.href)),
  );
  const view = await readView(client);
  const iframe = await loadSandbox(sandboxUrl(), view.permissions);

  const bridge = createBridge(client);
  const initialized = new Promise<void>((resolve) => {
    bridge.oninitialized = () => resolve();
  });
  await bridge.connect(
    new QuietPostMessageTransport(iframe.contentWindow!, iframe.contentWindow!),
  );
  await bridge.sendSandboxResourceReady(view);
  await initialized;
  // The app fills the page, so its keyboard shortcuts work without a click into it first.
  iframe.focus();
}

main().catch((cause: unknown) => {
  const status = document.getElementById("status")!;
  status.textContent = `Could not open the app. ${cause instanceof Error ? cause.message : String(cause)} Check that what served it, \`reality-check app\` or an agent session, is still running, then reload.`;
  status.hidden = false;
  document.querySelector("iframe")?.remove();
});
