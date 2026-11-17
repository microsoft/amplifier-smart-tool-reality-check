import {
  AppBridge,
  buildAllowAttribute,
  type McpUiResourcePermissions,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import type {
  CallToolResult,
  ReadResourceResult,
} from "@modelcontextprotocol/client";

import type {
  AppState,
  CheckActivity,
  CheckDetail,
  CheckEvent,
  CheckReference,
  CheckSummary,
} from "../src/lib/api";
import { QuietPostMessageTransport } from "../src/lib/transport";
import { parseContent, type Content } from "./content";

const HOST = { name: "Reality Check example", version: "1.0.0" };
const EVIDENCE_PREFIX = "reality-check://checks/";
// What `VIEW_META` in tools.py asks for.
const PERMISSIONS: McpUiResourcePermissions = { clipboardWrite: {} };
// `VIEW_CSP` in server.py, the policy `reality-check app` serves the view with.
const VIEW_CSP =
  "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
  "font-src 'self' data:; media-src 'self' data:; connect-src 'none'; frame-src 'none'; object-src 'none'; " +
  "base-uri 'self'";
// `SHORTENED_LENGTH` and `FULL_FIELDS` in schemas.py, which give an event's short form.
const SHORTENED_LENGTH = 500;
const FULL_FIELDS = ["arguments", "result", "detailed_result"];

type Check = { detail: CheckDetail; events: CheckEvent[] };

class ToolError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

async function fetched(path: string): Promise<Response> {
  const response = await fetch(new URL(path, location.href));
  if (!response.ok) {
    throw new Error(`${path} answered ${response.status}.`);
  }
  return response;
}

/** `quote` in Python's urllib, as `_cited` in checks.py uses it. */
function quote(path: string): string {
  return path.replace(/[^A-Za-z0-9_.~/-]/gu, (character) =>
    Array.from(new TextEncoder().encode(character))
      .map((byte) => `%${byte.toString(16).toUpperCase().padStart(2, "0")}`)
      .join(""),
  );
}

/** `_cited` in checks.py: whether the report names the file by its path in the check, or inside the evidence folder. */
function cited(path: string, report: string): boolean {
  const inside = path.replace(/^evidence\//, "");
  return [path, quote(path), inside, quote(inside)].some((name) => {
    const literal = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(?<![\\w./-])${literal}(?![\\w/-])`).test(report);
  });
}

/**
 * The check, with the request and report from the content: the request where the record and its first event keep it,
 * and the report as the check's report, its agent's last message, and what its last event ended with.
 */
async function readCheck(content: Content): Promise<Check> {
  const [detail, lines] = await Promise.all([
    fetched("./detail.json").then(
      (response) => response.json() as Promise<CheckDetail>,
    ),
    fetched("./events.jsonl").then((response) => response.text()),
  ]);
  const { request, report } = content;
  const events = lines
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as CheckEvent);
  const said = events.findLast((event) => event.kind === "progress");
  return {
    detail: {
      ...detail,
      check: { ...detail.check, request },
      report,
      evidence: detail.evidence.map((item) => ({
        ...item,
        referenced: cited(item.path, report),
      })),
    },
    events: events.map((event) =>
      event.kind === "started"
        ? { ...event, data: { ...event.data, request } }
        : event === said
          ? { ...event, text: report }
          : event.kind === "finished"
            ? { ...event, data: { ...event.data, report } }
            : event,
    ),
  };
}

/** The example's words, which the website writes from site/site.yaml. */
async function readContent(): Promise<Content> {
  const response = await fetched("./content.json");
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new Error("content.json is not JSON.");
  }
  return parseContent(value);
}

/** The example's view, under the policy `reality-check app` serves the app's view with. */
async function readView(): Promise<string> {
  const html = await (await fetched("./view.html")).text();
  return html.replace(
    "<head>",
    `<head><meta http-equiv="Content-Security-Policy" content="${VIEW_CSP}">`,
  );
}

/** `_cut` in schemas.py. */
function cut(value: unknown, line: number): unknown {
  if (typeof value === "string") {
    return value.length <= SHORTENED_LENGTH
      ? value
      : `${value.slice(0, SHORTENED_LENGTH)}...[cut at ${SHORTENED_LENGTH.toLocaleString("en-US")} of ${value.length.toLocaleString("en-US")} chars; full: line ${line} of events.jsonl]`;
  }
  if (Array.isArray(value)) {
    return value.map((item) => cut(item, line));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, cut(item, line)]),
    );
  }
  return value;
}

/** `brief` in schemas.py: an event's short form. */
function brief(event: CheckEvent): CheckEvent {
  let data = { ...event.data };
  if (
    event.kind === "started" &&
    data.agent_request &&
    typeof data.agent_request === "object"
  ) {
    const request = { ...(data.agent_request as Record<string, unknown>) };
    delete request.initial_message;
    data.agent_request = request;
  }
  if (event.kind === "tool") {
    data = Object.fromEntries(
      Object.entries(data).filter(([key]) => !FULL_FIELDS.includes(key)),
    );
  }
  data = Object.fromEntries(
    Object.entries(data).map(([key, value]) => [
      key,
      event.kind === "finished" && key === "report"
        ? value
        : cut(value, event.id),
    ]),
  );
  return { ...event, text: cut(event.text, event.id) as string, data };
}

function integer(value: unknown): number | undefined {
  return Number.isInteger(value) ? (value as number) : undefined;
}

function summaryOf({
  check,
  state,
  project,
  report,
}: CheckDetail): CheckSummary {
  return {
    check_id: check.check_id,
    project,
    request: check.request,
    target: check.target,
    state,
    started_at: check.started_at,
    ended_at: check.ended_at,
    agent_provider: check.agent_provider,
    model: check.model,
    origin: check.origin,
    resume: check.resume,
    has_report: report !== null,
  };
}

function referenceOf({ check, project }: CheckDetail): CheckReference {
  return {
    check_id: check.check_id,
    checks_directory: project.checks_directory,
  };
}

function activity(
  { detail, events }: Check,
  args: Record<string, unknown>,
): CheckActivity {
  const after = integer(args.after_event);
  const before = integer(args.before_event);
  const tail = integer(args.tail_events);
  const last = events.at(-1)?.id ?? 0;
  if (after !== undefined && after > last) {
    throw new ToolError(
      "event-not-found",
      `Check ${detail.check.check_id} has no event ${after}; its last is ${last}.`,
    );
  }
  let picked = events
    .filter(
      (event) =>
        event.kind !== "usage" &&
        (after === undefined || event.id > after) &&
        (before === undefined || event.id < before),
    )
    .map((event) => (args.truncate === false ? event : brief(event)));
  if (tail !== undefined) {
    picked = tail ? picked.slice(-tail) : [];
  }
  return {
    check: detail.check,
    state: detail.state,
    process_log: null,
    events: picked,
  };
}

function answer(
  check: Check,
  name: string,
  args: Record<string, unknown>,
): Record<string, unknown> {
  const reference = referenceOf(check.detail);
  if (name === "list_checks") {
    const state: AppState = {
      checks: [summaryOf(check.detail)],
      focus: reference,
      opened: 1,
      can_open_folders: false,
    };
    return state;
  }
  if (
    args.check_id !== reference.check_id ||
    args.checks_directory !== reference.checks_directory
  ) {
    throw new ToolError(
      "check-not-found",
      `No check '${String(args.check_id)}' in this example.`,
    );
  }
  if (name === "read_check") {
    return check.detail;
  }
  if (name === "read_check_activity") {
    return activity(check, args);
  }
  if (name === "open_check_folder") {
    throw new ToolError(
      "cannot-open-folder",
      "This example runs in a web page, so it has no folder to open.",
    );
  }
  throw new Error(`No tool '${name}'. The tools are the view's.`);
}

function callTool(
  check: Check,
  name: string,
  args: Record<string, unknown>,
): CallToolResult {
  try {
    const structured = answer(check, name, args);
    return {
      content: [{ type: "text", text: JSON.stringify(structured) }],
      structuredContent: structured,
    };
  } catch (error) {
    if (!(error instanceof ToolError)) {
      throw error;
    }
    return {
      content: [{ type: "text", text: error.message }],
      structuredContent: { code: error.code },
      isError: true,
    };
  }
}

function base64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

async function readEvidence(
  { detail }: Check,
  uri: string,
): Promise<ReadResourceResult> {
  const [directory, checkId, ...rest] = uri
    .slice(EVIDENCE_PREFIX.length)
    .split("/");
  const path = rest.map(decodeURIComponent).join("/");
  const entry = detail.evidence.find((item) => item.path === path);
  if (
    !uri.startsWith(EVIDENCE_PREFIX) ||
    decodeURIComponent(directory ?? "") !== detail.project.checks_directory ||
    decodeURIComponent(checkId ?? "") !== detail.check.check_id ||
    !entry
  ) {
    throw new Error(
      `${path} is not a path inside the check's evidence folder.`,
    );
  }
  const file = await fetched(`./${rest.join("/")}`);
  return {
    contents: [
      {
        uri,
        mimeType: entry.media_type,
        blob: await base64(await file.blob()),
      },
    ],
  };
}

function frame(): HTMLIFrameElement {
  const iframe = document.createElement("iframe");
  iframe.title = "Reality Check, showing an example check";
  // Without allow-same-origin the view runs in an origin of its own, apart from this page.
  iframe.setAttribute("sandbox", "allow-scripts allow-forms");
  iframe.setAttribute("allow", buildAllowAttribute(PERMISSIONS));
  return iframe;
}

function createBridge(check: Check): AppBridge {
  const bridge = new AppBridge(
    null,
    HOST,
    { openLinks: {}, serverTools: {}, serverResources: {} },
    {
      // The page around it is light, so the view starts light; its settings still offer dark.
      hostContext: {
        theme: "light",
        platform: "web",
        displayMode: "inline",
        availableDisplayModes: ["inline"],
        containerDimensions: {
          width: window.innerWidth,
          height: window.innerHeight,
        },
      },
    },
  );
  bridge.oncalltool = async ({ name, arguments: args }) =>
    callTool(check, name, args ?? {});
  bridge.onreadresource = async ({ uri }) => readEvidence(check, uri);
  bridge.onopenlink = async ({ url }) => {
    window.open(url, "_blank", "noopener,noreferrer");
    return {};
  };
  bridge.onrequestdisplaymode = async () => ({ mode: "inline" });
  // The view keeps its own height inline, and this page is its frame.
  bridge.onsizechange = () => {};
  window.addEventListener("resize", () =>
    bridge.sendHostContextChange({
      containerDimensions: {
        width: window.innerWidth,
        height: window.innerHeight,
      },
    }),
  );
  return bridge;
}

async function main(): Promise<void> {
  const content = await readContent();
  const [check, html] = await Promise.all([readCheck(content), readView()]);
  const iframe = frame();
  const bridge = createBridge(check);
  const initialized = new Promise<void>((resolve) => {
    bridge.oninitialized = () => resolve();
  });
  document.body.append(iframe);
  // Listening before the view loads, so its first message is heard.
  await bridge.connect(
    new QuietPostMessageTransport(iframe.contentWindow!, iframe.contentWindow!),
  );
  iframe.srcdoc = html;
  await initialized;
  // What a host does when an agent calls `open_app` for this check: it opens on the check.
  const focus = referenceOf(check.detail);
  await bridge.sendToolInput({ arguments: focus });
  await bridge.sendToolResult({
    content: [
      {
        type: "text",
        text: `The app is shown inline. It opens on check ${focus.check_id}.`,
      },
    ],
    // The gallery rides along, so the view shows it under the report.
    structuredContent: { url: location.href, focus, gallery: content.gallery },
  });
}

main().catch((cause: unknown) => {
  const status = document.getElementById("status")!;
  status.textContent = `The example could not load. ${cause instanceof Error ? cause.message : String(cause)}`;
  status.hidden = false;
  document.querySelector("iframe")?.remove();
});
