import type { IconName } from "@/components/ui/icon";
import type { CheckEvent } from "@/lib/api";
import type { Evidence } from "@/lib/evidence";

export type ToolStep = {
  kind: "tool";
  key: string;
  /** The call's tool_call_id. */
  id: string;
  /** The ids of its call event and, once it has one, its result event, which read it in full. */
  event: number;
  resultEvent: number | null;
  name: string;
  verb: string;
  target: string;
  icon: IconName;
  /** What the call was given, as far as its activity line shows it. */
  brief: string;
  /** Its result, as far as its activity line shows it. */
  result: string | null;
  success: boolean | null;
  started: string;
  finished: string | null;
  /** The sub-agent that made the call, if it was not the check's own agent. */
  agent: string | null;
  /** An evidence file the call looked at, ran, or wrote, which opens in the viewer. */
  evidence: string | null;
};

export type ReasoningStep = {
  kind: "reasoning";
  key: string;
  time: string;
  title: string;
  text: string;
};

export type Step = ToolStep | ReasoningStep;

export type Block =
  | {
      kind: "request";
      key: string;
      time: string;
      text: string;
      origin: string | null;
    }
  | { kind: "said"; key: string; time: string; text: string }
  | {
      kind: "steps";
      key: string;
      steps: Step[];
      started: string;
      finished: string | null;
      running: boolean;
    }
  | {
      kind: "steered";
      key: string;
      time: string;
      text: string;
      origin: string | null;
      data: Record<string, unknown>;
    }
  | {
      kind: "ended";
      key: string;
      time: string;
      status: string;
      text: string;
      remedy: string | null;
    };

function str(value: unknown): string {
  return typeof value === "string"
    ? value
    : value === undefined
      ? ""
      : JSON.stringify(value);
}

/** The evidence path an argument stands for: anything under an evidence/ folder, wherever the agent kept it. */
function evidencePath(path: string): string | null {
  const match = /(?:^|[/\\\s"'`=])(evidence\/[^\s"'`),;]+)/.exec(path);
  return match ? match[1].replace(/[.:]+$/, "") : null;
}

function basename(path: string): string {
  return path.split("/").filter(Boolean).at(-1) ?? path;
}

/** A tool line's name and arguments: the line is the tool's name, then its arguments as JSON, cut short when long. */
function parseTool(
  text: string,
  name: string,
): { args: Record<string, unknown>; raw: string } {
  const raw = text.startsWith(name) ? text.slice(name.length).trim() : text;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return { args: parsed as Record<string, unknown>, raw };
    }
  } catch {
    // Cut short, so it is read field by field below.
  }
  const args: Record<string, unknown> = {};
  for (const match of raw.matchAll(/"(\w+)":\s*"((?:[^"\\]|\\.)*)/g)) {
    try {
      args[match[1]] = JSON.parse(`"${match[2]}"`);
    } catch {
      args[match[1]] = match[2];
    }
  }
  return { args, raw };
}

/** What a tool call did, in a few words: a plain verb, what it acted on, and its icon. */
function describe(
  name: string,
  args: Record<string, unknown>,
  raw: string,
): Pick<ToolStep, "verb" | "target" | "icon" | "evidence"> {
  switch (name) {
    case "bash":
    case "shell":
    case "exec_command":
    case "Bash": {
      const command = str(args.command ?? args.cmd).split("\n")[0] || raw;
      const script = /(?:python3?|node|bash|sh)\s+(\S+\.(?:py|js|mjs|sh))/.exec(
        command,
      );
      return {
        verb: script ? "Ran script" : "Ran",
        target: script ? basename(script[1]) : command.slice(0, 160),
        icon: "terminal",
        evidence: script ? evidencePath(script[1]) : null,
      };
    }
    case "view":
    case "Read":
    case "read_file": {
      const path = str(args.path ?? args.file_path);
      const evidence = evidencePath(path);
      const image = /\.(png|jpe?g|webp)$/i.test(path);
      return {
        verb: image ? "Looked at" : "Read",
        target: evidence ?? basename(path),
        icon: image ? "image" : "file",
        evidence,
      };
    }
    case "create":
    case "Write":
    case "edit":
    case "Edit":
    case "apply_patch": {
      const patch = /\*\*\* (Add|Update|Delete) File: (\S+)/.exec(
        str(args.input ?? args.patch ?? raw),
      );
      const path = patch?.[2] ?? str(args.path ?? args.file_path);
      const created =
        name === "create" || name === "Write" || patch?.[1] === "Add";
      return {
        verb: created
          ? "Wrote"
          : patch?.[1] === "Delete"
            ? "Deleted"
            : "Edited",
        target: evidencePath(path) ?? basename(path),
        icon: "file-edit",
        evidence: evidencePath(path),
      };
    }
    case "skill":
      return {
        verb: "Loaded skill",
        target: str(args.skill),
        icon: "layers",
        evidence: null,
      };
    case "task":
    case "Task":
      return {
        verb: "Started agent",
        target: str(args.name ?? args.description),
        icon: "model",
        evidence: null,
      };
    case "write_agent":
      return {
        verb: "Messaged agent",
        target: str(args.message).slice(0, 140),
        icon: "message",
        evidence: null,
      };
    case "read_agent":
      return {
        verb: "Read agent",
        target: str(args.agent_id).slice(0, 8),
        icon: "message",
        evidence: null,
      };
    case "glob":
    case "Glob":
    case "grep":
    case "Grep":
      return {
        verb: "Searched",
        target: str(args.pattern),
        icon: "search",
        evidence: null,
      };
    default:
      return {
        verb: name,
        target: raw.slice(0, 160),
        icon: "sliders",
        evidence: evidencePath(raw),
      };
  }
}

function reasoningTitle(text: string): string {
  const bold = /^\*\*(.+?)\*\*/.exec(text.trim());
  return bold ? bold[1] : text.trim().split("\n")[0].slice(0, 80);
}

/**
 * The events as the timeline shows them: the request, what the agent said, runs of steps between, steering, and the
 * ending. `request` is the check's whole request, which a `started` event's short form may cut.
 */
export function blocksOf(
  events: CheckEvent[],
  running: boolean,
  request?: string,
): Block[] {
  const blocks: Block[] = [];
  let group: Extract<Block, { kind: "steps" }> | null = null;
  const calls = new Map<string, ToolStep>();
  const close = () => {
    group = null;
  };
  const open = (time: string, key: string) => {
    if (!group) {
      // Keyed by its first event, so a block keeps its key as later events arrive.
      group = {
        kind: "steps",
        key: `steps-${key}`,
        steps: [],
        started: time,
        finished: null,
        running: false,
      };
      blocks.push(group);
    }
    return group;
  };

  events.forEach((event, index) => {
    const data = event.data ?? {};
    switch (event.kind) {
      case "started":
        close();
        blocks.push({
          kind: "request",
          key: `request-${index}`,
          time: event.time,
          text: request ?? str(data.request),
          origin: typeof data.origin === "string" ? data.origin : null,
        });
        break;
      case "progress":
        close();
        blocks.push({
          kind: "said",
          key: `said-${index}`,
          time: event.time,
          text: event.text,
        });
        break;
      case "steered":
        close();
        blocks.push({
          kind: "steered",
          key: `steered-${index}`,
          time: event.time,
          text: event.text,
          origin: typeof data.origin === "string" ? data.origin : null,
          data,
        });
        break;
      case "finished":
      case "failed":
        close();
        blocks.push({
          kind: "ended",
          key: `ended-${index}`,
          time: event.time,
          status: typeof data.status === "string" ? data.status : "failed",
          text: event.text,
          remedy: typeof data.remedy === "string" ? data.remedy : null,
        });
        break;
      case "reasoning": {
        const target = open(event.time, String(index));
        target.steps.push({
          kind: "reasoning",
          key: `reasoning-${index}`,
          time: event.time,
          title: reasoningTitle(event.text),
          text: event.text,
        });
        target.finished = event.time;
        break;
      }
      case "tool": {
        if (data.phase === "result") {
          const step = calls.get(str(data.tool_call_id));
          if (step) {
            step.result = event.text;
            step.success = data.success !== false;
            step.finished = event.time;
            step.resultEvent = event.id;
          }
          if (group) {
            group.finished = event.time;
          }
          break;
        }
        const id = str(data.tool_call_id);
        const target = open(event.time, String(index));
        const name = str(data.tool_name) || event.text.split(" ")[0];
        const { args, raw } = parseTool(event.text, name);
        const step: ToolStep = {
          kind: "tool",
          key: `tool-${id || index}`,
          id,
          event: event.id,
          resultEvent: null,
          name,
          ...describe(name, args, raw),
          brief: raw,
          result: null,
          success: null,
          started: event.time,
          finished: null,
          agent: typeof data.agent_id === "string" ? data.agent_id : null,
        };
        calls.set(id, step);
        target.steps.push(step);
        break;
      }
    }
  });

  const last = blocks.at(-1);
  if (running && last?.kind === "steps") {
    last.running = true;
  }
  return blocks;
}

/** The step a running check is on: its latest tool call, and how many it has made. */
export function currentStep(
  blocks: Block[],
): { verb: string; target: string; count: number } | null {
  const steps = toolSteps(blocks);
  const latest = steps.at(-1);
  return latest
    ? { verb: latest.verb, target: latest.target, count: steps.length }
    : null;
}

export function latestSaid(events: CheckEvent[]): CheckEvent | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index].kind === "progress") {
      return events[index];
    }
  }
  return null;
}

/** Tool steps in order, flattened out of their blocks. */
export function toolSteps(blocks: Block[]): ToolStep[] {
  return blocks.flatMap((block) =>
    block.kind === "steps"
      ? block.steps.filter((step): step is ToolStep => step.kind === "tool")
      : [],
  );
}

/** Screenshots saved while a step ran, from just before it started to just after it finished. */
export function producedBy(step: ToolStep, evidence: Evidence[]): Evidence[] {
  const start = Date.parse(step.started) - 500;
  const end = Date.parse(step.finished ?? step.started) + 1500;
  return evidence.filter((item) => {
    const time = Date.parse(item.modified_at);
    return item.kind === "screenshot" && time >= start && time <= end;
  });
}

/**
 * The step that stands for an evidence file in the activity: the call that wrote or ran it by name, else the call
 * running when it was saved, else the last call before.
 */
export function stepFor(
  path: string,
  evidence: Evidence[],
  steps: ToolStep[],
): ToolStep | null {
  const named = steps.find(
    (step) => step.evidence === path && step.verb !== "Looked at",
  );
  if (named) {
    return named;
  }
  const item = evidence.find((each) => each.path === path);
  if (!item) {
    return steps.find((step) => step.evidence === path) ?? null;
  }
  const time = Date.parse(item.modified_at);
  const during = steps.filter(
    (step) =>
      Date.parse(step.started) - 500 <= time &&
      time <= Date.parse(step.finished ?? step.started) + 1500,
  );
  if (during.length > 0) {
    return during[during.length - 1];
  }
  const before = steps.filter((step) => Date.parse(step.started) <= time);
  return before.at(-1) ?? steps.find((step) => step.evidence === path) ?? null;
}
