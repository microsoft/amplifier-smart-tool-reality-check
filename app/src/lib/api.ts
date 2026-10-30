import type { CallToolResult } from "@modelcontextprotocol/client";

import { AppError, codeFromMessage } from "@/lib/errors";
import { app } from "@/lib/host";

const EVIDENCE_PREFIX = "reality-check://checks/";

/** `CheckState` in schemas.py: how a check ran, never what it found. */
export type CheckState =
  "running" | "crashed" | "done" | "cancelled" | "timed-out" | "failed";

/** `Project` in schemas.py. */
export type Project = { root: string; checks_directory: string };

/** `CheckReference` in schemas.py. */
export type CheckReference = { check_id: string; checks_directory: string };

/** `CheckSummary` in schemas.py. */
export type CheckSummary = {
  check_id: string;
  project: Project;
  request: string;
  target: string | null;
  state: CheckState;
  started_at: string;
  ended_at: string | null;
  agent_provider: string;
  model: string;
  origin: string;
  /** The check this one continues, in the same checks directory. */
  resume: string | null;
  has_report: boolean;
};

/** `CheckUsage` in schemas.py. */
export type CheckUsage = {
  model_calls: number;
  fresh_input_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  billing: Record<string, number>;
};

/** The fields of `CheckRecord` in schemas.py that the view reads. */
export type CheckRecord = {
  check_id: string;
  request: string;
  target: string | null;
  resume: string | null;
  previous_checks: string[] | null;
  ask_first: string;
  keep_running: boolean;
  agent_provider: string;
  model: string;
  reasoning_effort: string | null;
  session_id: string | null;
  status: string;
  timeout_seconds: number | null;
  usage: CheckUsage;
  started_at: string;
  ended_at: string | null;
  pid: number | null;
  last_event: string | null;
  origin: string;
  images: string[] | null;
  detached: boolean;
};

/** `EvidenceEntry` in schemas.py. */
export type EvidenceEntry = {
  /** Relative to the check's directory, such as `evidence/01-home.png`. */
  path: string;
  media_type: string;
  size: number;
  modified_at: string;
  /** Whether the report cites it. */
  referenced: boolean;
};

/** `CheckDetail` in schemas.py. */
export type CheckDetail = {
  check: CheckRecord;
  state: CheckState;
  project: Project;
  directory: string;
  /** Markdown, every path into the check's evidence folder written as `evidence/<name>`. */
  report: string | null;
  evidence: EvidenceEntry[];
  resumes: CheckReference | null;
  previous_checks: CheckReference[];
};

/** `CheckEventKind` in schemas.py; reads never return `usage`. */
export type CheckEventKind =
  | "started"
  | "progress"
  | "reasoning"
  | "tool"
  | "usage"
  | "steered"
  | "finished"
  | "failed";

/** `CheckEvent` in schemas.py. */
export type CheckEvent = {
  /** Its line in the check's events.jsonl, from 1. */
  id: number;
  check_id: string;
  time: string;
  kind: CheckEventKind;
  text: string;
  data: Record<string, unknown>;
};

/** `CheckActivity` in schemas.py. */
export type CheckActivity = {
  check: CheckRecord;
  state: CheckState;
  process_log: string | null;
  events: CheckEvent[];
};

/** How the short form ends a string it cut, as `_cut` in schemas.py writes it. */
const CUT_MARKER =
  /\.\.\.\[cut at [\d,]+ of [\d,]+ chars; full: line \d+ of events\.jsonl\]$/;

/** Whether the short form cut `text`, so the event is read whole for it. */
export function isCut(text: string): boolean {
  return CUT_MARKER.test(text);
}

/** A tool call and, once it has one, its result, each as events.jsonl keeps it. */
export type ToolCall = { call: CheckEvent | null; result: CheckEvent | null };

/** What `list_checks` returns: every check, and the one the app was last asked to open, counted. */
export type AppState = {
  checks: CheckSummary[];
  focus: CheckReference | null;
  opened: number;
  /** Whether the server's machine can show a folder in a file manager. */
  can_open_folders: boolean;
};

/** What `open_app` returns. */
export type OpenedApp = { url: string; focus: CheckReference | null };

/** An evidence file as the server sends it. */
export type EvidenceData = { base64: string; mimeType: string };

function textOf(result: CallToolResult): string {
  return result.content
    .flatMap((block) => (block.type === "text" ? [block.text] : []))
    .join(" ");
}

async function call(
  name: string,
  args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const result = await app.callServerTool({ name, arguments: args });
  const structured = result.structuredContent as
    Record<string, unknown> | undefined;
  if (result.isError) {
    throw new AppError(
      textOf(result) || `\`${name}\` failed.`,
      typeof structured?.code === "string" ? structured.code : null,
    );
  }
  if (!structured) {
    throw new AppError(
      `\`${name}\` returned nothing. Check that the server is Reality Check.`,
    );
  }
  return structured;
}

function referenceArguments(ref: CheckReference) {
  return { check_id: ref.check_id, checks_directory: ref.checks_directory };
}

/** Every check on this machine, newest first, and the check the app was last asked to open. */
export async function listChecks(): Promise<AppState> {
  const structured = await call("list_checks", {});
  if (!Array.isArray(structured.checks)) {
    throw new AppError(
      "`list_checks` returned no checks. Check that the server is this version of Reality Check.",
    );
  }
  return structured as AppState;
}

/** A check as it stands, with its report and the evidence it has so far. */
export async function readCheck(ref: CheckReference): Promise<CheckDetail> {
  return (await call("read_check", referenceArguments(ref))) as CheckDetail;
}

/** A check's events in short form, or only those after the event `afterEvent`. */
export async function readCheckActivity(
  ref: CheckReference,
  afterEvent?: number,
): Promise<CheckActivity> {
  const args = referenceArguments(ref);
  return (await call(
    "read_check_activity",
    afterEvent === undefined ? args : { ...args, after_event: afterEvent },
  )) as CheckActivity;
}

/** A check's events with ids between `afterEvent` and `beforeEvent`, as events.jsonl keeps them. */
async function readWhole(
  ref: CheckReference,
  afterEvent: number,
  beforeEvent: number,
): Promise<CheckEvent[]> {
  const activity = (await call("read_check_activity", {
    ...referenceArguments(ref),
    after_event: afterEvent,
    before_event: beforeEvent,
    truncate: false,
  })) as CheckActivity;
  return activity.events;
}

/** One event of a check as events.jsonl keeps it, or null when the check has no such event. */
export async function readEvent(
  ref: CheckReference,
  id: number,
): Promise<CheckEvent | null> {
  const events = await readWhole(ref, id - 1, id + 1);
  return events.find((event) => event.id === id) ?? null;
}

/**
 * One tool call of a check's agent in full, by the ids of its call event and, once it has one, its result event; the
 * result is the event between them that answers the call.
 */
export async function readToolCall(
  ref: CheckReference,
  callEvent: number,
  resultEvent: number | null,
): Promise<ToolCall> {
  const events = await readWhole(
    ref,
    callEvent - 1,
    (resultEvent ?? callEvent) + 1,
  );
  const called = events.find((event) => event.id === callEvent) ?? null;
  const toolCallId = called?.data.tool_call_id;
  const result =
    toolCallId === undefined
      ? null
      : (events.find(
          (event) =>
            event.kind === "tool" &&
            event.data.phase === "result" &&
            event.data.tool_call_id === toolCallId,
        ) ?? null);
  return { call: called, result };
}

/** Shows a check's folder in the file manager of the machine the server runs on; resolves with that folder. */
export async function openCheckFolder(ref: CheckReference): Promise<string> {
  const structured = await call("open_check_folder", referenceArguments(ref));
  return String(structured.opened ?? "");
}

/** One file from a check's evidence folder, `path` such as `evidence/01-home.png`. */
export async function readEvidence(
  ref: CheckReference,
  path: string,
): Promise<EvidenceData> {
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  const uri = `${EVIDENCE_PREFIX}${encodeURIComponent(ref.checks_directory)}/${encodeURIComponent(ref.check_id)}/${encoded}`;
  let contents;
  try {
    ({ contents } = await app.readServerResource({ uri }));
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause);
    throw new AppError(message, codeFromMessage(message));
  }
  const content = contents[0];
  if (!content || !("blob" in content)) {
    throw new AppError(`${uri} came back without its file.`);
  }
  return {
    base64: content.blob,
    mimeType: content.mimeType ?? "application/octet-stream",
  };
}
