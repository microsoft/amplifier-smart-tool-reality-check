import { useSyncExternalStore } from "react";

import {
  listChecks,
  readCheck,
  readCheckActivity,
  type ActivityEntry,
  type CheckDetail,
  type CheckRecord,
  type CheckReference,
  type CheckState,
  type CheckSummary,
} from "@/lib/api";
import { AppError } from "@/lib/errors";
import { toEvidence, type Evidence } from "@/lib/evidence";
import { onOpened } from "@/lib/host";

const LIST_MS = 10_000;
const DETAIL_MS = 2_000;
const ACTIVITY_MS = 1_000;

/** A project checks were started from, with its checks newest first. */
export type ProjectGroup = {
  root: string;
  checks_directory: string;
  /** The project folder's name in words; its full path goes in a tooltip. */
  name: string;
  checks: CheckSummary[];
};

/** A check's activity as read so far, and where the next read starts. */
export type ActivityLog = {
  entries: ActivityEntry[];
  cursor: number;
  processLog: string | null;
};

/** The selected check, put together from its summary, its detail, and its activity as far as each is read. */
export type Check = {
  key: string;
  ref: CheckReference;
  id: string;
  summary: CheckSummary;
  state: CheckState;
  /** The request's first line, as lists and titles show it. */
  label: string;
  project: ProjectGroup | null;
  detail: CheckDetail | null;
  record: CheckRecord | null;
  report: string | null;
  evidence: Evidence[];
  activity: ActivityLog | null;
  directory: string | null;
  error: unknown;
  activityError: unknown;
  /** Checks in this list that continue this one in the same agent session. */
  continuedBy: CheckSummary[];
};

type State = {
  phase: "loading" | "ready" | "error";
  /** The first read of the list failed, so there is nothing to show. */
  error: unknown;
  /** A later read of the list failed; the list shown is the last one read. */
  listError: unknown;
  checks: CheckSummary[];
  projects: ProjectGroup[];
  /** Whether the server's machine can show a check's folder in a file manager. */
  canOpenFolders: boolean;
  selected: CheckReference | null;
  details: Record<string, CheckDetail>;
  detailErrors: Record<string, unknown>;
  activities: Record<string, ActivityLog>;
  activityErrors: Record<string, unknown>;
  /** The freshest state each check was read in, from whichever read came last. */
  states: Record<string, { state: CheckState; record: CheckRecord }>;
  check: Check | null;
};

let state: State = {
  phase: "loading",
  error: null,
  listError: null,
  checks: [],
  projects: [],
  canOpenFolders: false,
  selected: null,
  details: {},
  detailErrors: {},
  activities: {},
  activityErrors: {},
  states: {},
  check: null,
};
const listeners = new Set<() => void>();
let lastOpened = 0;
let listTimer: ReturnType<typeof setTimeout> | undefined;
let checkTimer: ReturnType<typeof setTimeout> | undefined;
let generation = 0;
let detailDue = 0;
const inFlight = new Map<string, Promise<void>>();
// What each read last returned, as JSON, so a poll that finds nothing new renders nothing.
let listedJson = "";
const detailJson = new Map<string, string>();

export function keyOf(ref: CheckReference): string {
  return `${ref.checks_directory}\n${ref.check_id}`;
}

export function isRunning(checkState: CheckState | undefined): boolean {
  return checkState === "running";
}

/** A project's name as people read it: its folder's name in words, each capitalized, such as "My Project". */
export function projectName(root: string): string {
  const folder = root.split(/[\\/]/).filter(Boolean).at(-1) ?? root;
  const words = folder.split(/[-_.\s]+/).filter(Boolean);
  return (
    words
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ") || folder
  );
}

/** The first line of a request, for lists and titles. */
export function labelOf(request: string): string {
  return request.trim().split("\n")[0].trim() || "Check";
}

function hidden(): boolean {
  return document.visibilityState === "hidden";
}

function summaryFrom(detail: CheckDetail): CheckSummary {
  const record = detail.check;
  return {
    check_id: record.check_id,
    project: detail.project,
    request: record.request,
    target: record.target,
    state: detail.state,
    started_at: record.started_at,
    ended_at: record.ended_at,
    agent_provider: record.agent_provider,
    model: record.model,
    origin: record.origin,
    resume: record.resume,
    has_report: detail.report !== null,
  };
}

/** Which of two reads of a check's state is newer: a check only ever stops running, never starts again. */
function newer(one: CheckState, other: CheckState): CheckState {
  return isRunning(one) ? other : one;
}

/** The list as read, with the state of each check that a newer read of it saw stop running. */
function merged(checks: CheckSummary[]): CheckSummary[] {
  return checks.map((summary) => {
    const fresh =
      state.states[
        keyOf({
          check_id: summary.check_id,
          checks_directory: summary.project.checks_directory,
        })
      ];
    if (!fresh || !isRunning(summary.state) || isRunning(fresh.state)) {
      return summary;
    }
    return { ...summary, state: fresh.state, ended_at: fresh.record.ended_at };
  });
}

function group(checks: CheckSummary[]): ProjectGroup[] {
  const groups = new Map<string, ProjectGroup>();
  for (const summary of checks) {
    const directory = summary.project.checks_directory;
    let project = groups.get(directory);
    if (!project) {
      project = {
        root: summary.project.root,
        checks_directory: directory,
        name: projectName(summary.project.root),
        checks: [],
      };
      groups.set(directory, project);
    }
    project.checks.push(summary);
  }
  // Checks come newest first, so the project with the newest check comes first.
  return [...groups.values()];
}

const evidenceCache = new WeakMap<CheckDetail, Evidence[]>();

function evidenceOf(detail: CheckDetail | null): Evidence[] {
  if (!detail) {
    return [];
  }
  let evidence = evidenceCache.get(detail);
  if (!evidence) {
    evidence = detail.evidence.map(toEvidence);
    evidenceCache.set(detail, evidence);
  }
  return evidence;
}

function compose(previous: Check | null): Check | null {
  const ref = state.selected;
  if (!ref) {
    return null;
  }
  const key = keyOf(ref);
  const detail = state.details[key] ?? null;
  const listed = state.checks.find(
    (summary) =>
      summary.check_id === ref.check_id &&
      summary.project.checks_directory === ref.checks_directory,
  );
  const summary = listed ?? (detail ? summaryFrom(detail) : null);
  if (!summary) {
    return null;
  }
  const fresh = state.states[key];
  const activity = state.activities[key] ?? null;
  const error = state.detailErrors[key] ?? null;
  const activityError = state.activityErrors[key] ?? null;
  const project =
    state.projects.find(
      (each) => each.checks_directory === ref.checks_directory,
    ) ?? null;
  const continuedBy = state.checks.filter(
    (each) =>
      each.resume === ref.check_id &&
      each.project.checks_directory === ref.checks_directory,
  );
  if (
    previous &&
    previous.key === key &&
    previous.summary === summary &&
    previous.detail === detail &&
    previous.activity === activity &&
    previous.record === (fresh?.record ?? detail?.check ?? null) &&
    previous.error === error &&
    previous.activityError === activityError &&
    previous.project === project &&
    previous.continuedBy.length === continuedBy.length &&
    previous.continuedBy.every((each, index) => each === continuedBy[index])
  ) {
    return previous;
  }
  return {
    key,
    ref,
    id: ref.check_id,
    summary,
    state: newer(fresh?.state ?? detail?.state ?? summary.state, summary.state),
    label: labelOf(summary.request),
    project,
    detail,
    record: fresh?.record ?? detail?.check ?? null,
    report: detail?.report ?? null,
    evidence: evidenceOf(detail),
    activity,
    directory: detail?.directory ?? null,
    error,
    activityError,
    continuedBy,
  };
}

function set(change: Partial<State>) {
  state = { ...state, ...change };
  if ("checks" in change || "states" in change) {
    const checks = merged(state.checks);
    state = { ...state, checks, projects: group(checks) };
  }
  state = { ...state, check: compose(state.check) };
  for (const listener of listeners) {
    listener();
  }
}

function freshState(
  key: string,
  checkState: CheckState,
  record: CheckRecord,
): State["states"] {
  return { ...state.states, [key]: { state: checkState, record } };
}

/** Run `read` for `key` unless one is already going, so two reads never apply the same entries twice. */
function once(key: string, read: () => Promise<void>): Promise<void> {
  const going = inFlight.get(key);
  if (going) {
    return going;
  }
  const started = read().finally(() => inFlight.delete(key));
  inFlight.set(key, started);
  return started;
}

async function refreshList(): Promise<void> {
  try {
    const listed = await listChecks();
    const first = state.phase !== "ready";
    const canOpenFolders = listed.can_open_folders === true;
    if (canOpenFolders !== state.canOpenFolders) {
      set({ canOpenFolders });
    }
    const json = JSON.stringify(listed.checks);
    if (first || json !== listedJson || state.listError !== null) {
      listedJson = json;
      set({
        phase: "ready",
        error: null,
        listError: null,
        checks: listed.checks,
      });
    }
    if (listed.opened !== lastOpened) {
      lastOpened = listed.opened;
      if (listed.focus) {
        select(listed.focus);
        return;
      }
    }
    if (first && !state.selected && state.checks[0]) {
      select({
        check_id: state.checks[0].check_id,
        checks_directory: state.checks[0].project.checks_directory,
      });
    }
  } catch (cause) {
    if (state.phase === "ready") {
      set({ listError: cause });
    } else {
      set({ phase: "error", error: cause });
    }
  }
}

function refreshDetail(ref: CheckReference): Promise<void> {
  const key = keyOf(ref);
  return once(`detail\n${key}`, async () => {
    try {
      const detail = await readCheck(ref);
      const json = JSON.stringify(detail);
      if (detailJson.get(key) === json && !(key in state.detailErrors)) {
        return;
      }
      detailJson.set(key, json);
      const detailErrors = { ...state.detailErrors };
      delete detailErrors[key];
      set({
        details: { ...state.details, [key]: detail },
        detailErrors,
        states: freshState(key, detail.state, detail.check),
      });
    } catch (cause) {
      set({ detailErrors: { ...state.detailErrors, [key]: cause } });
    }
  });
}

function refreshActivity(ref: CheckReference): Promise<void> {
  const key = keyOf(ref);
  return once(`activity\n${key}`, async () => {
    const log = state.activities[key];
    try {
      let read;
      try {
        read = await readCheckActivity(ref, log?.cursor);
      } catch (cause) {
        // The log was replaced under the cursor, so it is read again from its start.
        if (
          !(cause instanceof AppError) ||
          cause.code !== "bad-cursor" ||
          !log
        ) {
          throw cause;
        }
        read = await readCheckActivity(ref);
        set({
          activities: {
            ...state.activities,
            [key]: { entries: [], cursor: 0, processLog: null },
          },
        });
      }
      const current = state.activities[key];
      const entries = current ? current.entries : [];
      const activityErrors = { ...state.activityErrors };
      delete activityErrors[key];
      const unchanged =
        current &&
        read.entries.length === 0 &&
        current.cursor === read.cursor &&
        current.processLog === read.process_log;
      set({
        activities: unchanged
          ? state.activities
          : {
              ...state.activities,
              [key]: {
                entries: read.entries.length
                  ? [...entries, ...read.entries]
                  : entries,
                cursor: read.cursor,
                processLog: read.process_log,
              },
            },
        activityErrors,
        states:
          state.states[key]?.state === read.state &&
          JSON.stringify(state.states[key]?.record) ===
            JSON.stringify(read.check)
            ? state.states
            : freshState(key, read.state, read.check),
      });
    } catch (cause) {
      set({ activityErrors: { ...state.activityErrors, [key]: cause } });
    }
  });
}

function scheduleList() {
  clearTimeout(listTimer);
  listTimer = setTimeout(async () => {
    if (hidden()) {
      return;
    }
    await refreshList();
    scheduleList();
  }, LIST_MS);
}

/**
 * Reads the selected check: its detail and activity once, then while it runs its activity every second and its
 * detail every two, and once more when it stops running so its report and last evidence show.
 */
async function pollCheck(token: number, first: boolean): Promise<void> {
  const ref = state.selected;
  if (!ref || token !== generation || hidden()) {
    return;
  }
  const key = keyOf(ref);
  const wasRunning = isRunning(state.states[key]?.state);
  const detailNow = first || Date.now() >= detailDue;
  await Promise.all([
    detailNow ? refreshDetail(ref) : null,
    refreshActivity(ref),
  ]);
  if (detailNow) {
    detailDue = Date.now() + DETAIL_MS;
  }
  if (token !== generation) {
    return;
  }
  if (isRunning(state.states[key]?.state)) {
    checkTimer = setTimeout(() => void pollCheck(token, false), ACTIVITY_MS);
  } else if (wasRunning || isRunning(state.details[key]?.state)) {
    await Promise.all([refreshDetail(ref), refreshActivity(ref)]);
  }
}

function restartCheckPolling() {
  clearTimeout(checkTimer);
  generation += 1;
  void pollCheck(generation, true);
}

/** Show `ref` and keep it read as it changes. */
export function select(ref: CheckReference) {
  const same =
    state.selected?.check_id === ref.check_id &&
    state.selected.checks_directory === ref.checks_directory;
  if (!same) {
    set({
      selected: {
        check_id: ref.check_id,
        checks_directory: ref.checks_directory,
      },
    });
    restartCheckPolling();
  }
}

/** Read the list and the selected check again now, as after the page comes back into view. */
export function refresh() {
  void refreshList().then(scheduleList);
  restartCheckPolling();
}

/** Read every check and start keeping them current; the view calls it once. */
export function start() {
  onOpened((opened) => {
    if (opened.focus) {
      select(opened.focus);
    }
    // The list counts the same opening, so it is read now to stop it from moving the selection again later.
    void refreshList();
  });
  document.addEventListener("visibilitychange", () => {
    if (!hidden()) {
      refresh();
    }
  });
  void refreshList().then(scheduleList);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useStore(): State {
  return useSyncExternalStore(subscribe, () => state);
}

/** How long a check has gone on, in seconds, counting up while it runs. */
export function elapsedSeconds(
  check: { state: CheckState; started_at: string; ended_at: string | null },
  now: number,
): number {
  const start = Date.parse(check.started_at);
  const end =
    check.ended_at && !isRunning(check.state)
      ? Date.parse(check.ended_at)
      : now;
  return Math.max(0, (end - start) / 1000);
}
