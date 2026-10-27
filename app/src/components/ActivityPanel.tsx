import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ErrorNotice } from "@/components/ErrorNotice";
import { EvidenceImage } from "@/components/EvidenceImage";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Markdown } from "@/components/ui/markdown";
import { ProgressBar } from "@/components/ui/progress-bar";
import { Elapsed } from "@/components/ui/status-mark";
import {
  blocksOf,
  currentStep,
  producedBy,
  stepFor,
  toolSteps,
  type Block,
  type Step,
  type ToolStep,
} from "@/lib/activity";
import { readToolCall, type ActivityEntry } from "@/lib/api";
import type { Evidence } from "@/lib/evidence";
import { plural } from "@/lib/format";
import { isRunning, type Check } from "@/lib/store";
import { between, offset, useNow } from "@/lib/time";
import { useUi } from "@/lib/ui";
import { cn } from "@/lib/utils";

const PINNED_PX = 48;

export type ActivityFocus = { path?: string; step?: string; nonce: number };

function Running({ since }: { since: string }) {
  const now = useNow(true);
  return <>{between(since, now)}</>;
}

function pretty(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (
    value &&
    typeof value === "object" &&
    "command" in value &&
    Object.keys(value).length <= 3
  ) {
    return String((value as { command: unknown }).command);
  }
  return JSON.stringify(value, null, 2);
}

const fullCalls = new Map<string, Promise<ActivityEntry[]>>();

/** A tool call's arguments and result in full, read when it is opened. */
function ToolDetail({ step, check }: { step: ToolStep; check: Check }) {
  const [read, setRead] = useState<{
    entries: ActivityEntry[] | null;
    error: unknown;
  }>({ entries: null, error: null });
  const finished = step.finished !== null;
  useEffect(() => {
    if (!step.id) {
      return;
    }
    // A call still running is read again once it has its result.
    const key = `${check.key}\n${step.id}\n${finished}`;
    let calls = fullCalls.get(key);
    if (!calls) {
      calls = readToolCall(check.ref, step.id);
      fullCalls.set(key, calls);
      calls.catch(() => fullCalls.delete(key));
    }
    let live = true;
    calls.then(
      (entries) => live && setRead({ entries, error: null }),
      (error: unknown) => live && setRead({ entries: null, error }),
    );
    return () => {
      live = false;
    };
  }, [check.key, check.ref, step.id, finished]);
  const call = read.entries?.find((entry) => entry.kind === "tool");
  const result = read.entries?.find((entry) => entry.kind === "tool-result");
  const args = call ? call.data.arguments : undefined;
  const output = result
    ? (result.data.result ?? result.data.detailed_result ?? result.text)
    : step.result;
  return (
    <div className="flex flex-col gap-2 border-t border-line bg-field px-2.5 py-2">
      {read.error !== null && (
        <ErrorNotice
          error={read.error}
          title="Could not read this step in full."
        />
      )}
      <div className="flex flex-col gap-1">
        <span className="text-caption text-ink-muted">
          {step.name}
          {step.agent && ", from a sub-agent"}
        </span>
        <pre className="max-h-80 overflow-auto rounded-sm border border-line bg-panel px-2 py-1.5 font-mono text-[11px]/4 whitespace-pre-wrap">
          {args !== undefined ? pretty(args) : step.brief}
        </pre>
      </div>
      {output !== null && output !== undefined && (
        <div className="flex flex-col gap-1">
          <span className="text-caption text-ink-muted">
            {step.success === false ? "Failed" : "Result"}
          </span>
          <pre className="max-h-96 overflow-auto rounded-sm border border-line bg-panel px-2 py-1.5 font-mono text-[11px]/4 whitespace-pre-wrap text-ink-muted">
            {pretty(output) || "No output"}
          </pre>
        </div>
      )}
      {!read.entries && read.error === null && step.id && (
        <span className="flex items-center gap-1.5 text-caption text-ink-muted">
          <LoadingMark />
          Reading the step in full
        </span>
      )}
    </div>
  );
}

/** Screenshots a step saved, small, each opening in the viewer. */
function Produced({
  check,
  items,
  onOpen,
}: {
  check: Check;
  items: Evidence[];
  onOpen: (item: Evidence) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1 pb-1.5 pl-8">
      {items.map((item) => (
        <button
          key={item.path}
          type="button"
          title={`Open ${item.name}`}
          onClick={() => onOpen(item)}
          className="h-10 w-15 overflow-hidden rounded-sm border border-line bg-field hover:border-line-control"
        >
          <EvidenceImage
            thumbnail
            checkRef={check.ref}
            item={item}
            className="size-full object-cover object-top"
          />
        </button>
      ))}
    </div>
  );
}

function StepRow({
  step,
  check,
  open,
  onToggle,
  flash,
}: {
  step: Step;
  check: Check;
  open: boolean;
  onToggle: () => void;
  flash: boolean;
}) {
  const { openEvidence } = useUi();
  const tool = step.kind === "tool" ? step : null;
  const running =
    tool !== null && tool.finished === null && isRunning(check.state);
  const produced = tool ? producedBy(tool, check.evidence) : [];
  const list = produced.map((item) => item.path);
  const evidence = tool?.evidence
    ? check.evidence.find((item) => item.path === tool.evidence)
    : undefined;
  return (
    <li
      data-step={step.key}
      className={cn(
        "border-t border-line transition-colors duration-700 first:border-t-0",
        flash && "bg-accent-soft",
      )}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        title={
          tool
            ? tool.target
            : step.kind === "reasoning"
              ? step.title
              : undefined
        }
        className={cn(
          "flex min-h-7 w-full min-w-0 items-center gap-2 px-2 text-left -outline-offset-2 hover:bg-hover",
          running && "bg-accent-soft",
        )}
      >
        <Icon
          name={
            step.kind === "reasoning" ? "thought" : (tool?.icon ?? "terminal")
          }
          className={cn(
            "shrink-0",
            running
              ? "text-accent-ink"
              : step.kind === "reasoning"
                ? "text-ink-faint"
                : "text-ink-muted",
          )}
        />
        {tool ? (
          <>
            <span className="shrink-0 text-label">{tool.verb}</span>
            <span className="min-w-0 flex-1 truncate mono-annotation text-ink-muted">
              {tool.target}
            </span>
            <span
              className={cn(
                "flex shrink-0 items-center gap-1.5 mono-annotation",
                running ? "text-accent-ink" : "text-ink-faint",
              )}
            >
              {running && <LoadingMark />}
              {running ? (
                <Running since={tool.started} />
              ) : (
                tool.finished && between(tool.started, tool.finished)
              )}
            </span>
          </>
        ) : (
          <span className="min-w-0 flex-1 truncate text-label font-normal text-ink-faint italic">
            {step.kind === "reasoning" ? step.title : ""}
          </span>
        )}
      </button>
      {produced.length > 0 && (
        <div className={cn(open && "border-t border-line pt-1.5")}>
          <Produced
            check={check}
            items={produced}
            onOpen={(item) => openEvidence(item.path, list)}
          />
        </div>
      )}
      {open && tool && (
        <>
          {evidence && (
            <div className="border-t border-line px-2 py-1.5">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => openEvidence(evidence.path, [evidence.path])}
              >
                <Icon name="eye" />
                Open {evidence.name}
              </Button>
            </div>
          )}
          <ToolDetail step={tool} check={check} />
        </>
      )}
      {open && step.kind === "reasoning" && (
        <div className="border-t border-line bg-field px-3 py-2 pl-8">
          <Markdown className="text-label font-normal text-ink-muted [&_strong]:text-ink-muted">
            {step.text}
          </Markdown>
        </div>
      )}
    </li>
  );
}

function StepBlock({
  block,
  check,
  open,
  onToggle,
  flashStep,
  shown,
  onShow,
}: {
  block: Extract<Block, { kind: "steps" }>;
  check: Check;
  open: boolean;
  onToggle: () => void;
  flashStep: string | null;
  shown: ReadonlySet<string>;
  onShow: (key: string) => void;
}) {
  const tools = block.steps.filter((step) => step.kind === "tool");
  const thoughts = block.steps.filter(
    (step) => step.kind === "reasoning",
  ).length;
  const shots = new Set(
    tools.flatMap((step) =>
      producedBy(step, check.evidence).map((item) => item.path),
    ),
  ).size;
  return (
    <li className="ml-4 shrink-0 overflow-hidden rounded-md border border-line bg-panel">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex h-7 w-full items-center gap-1.5 px-2 text-left text-label -outline-offset-2 hover:bg-hover"
      >
        <Icon
          name="chevron"
          className={cn(
            "shrink-0 text-ink-muted transition-transform",
            !open && "-rotate-90",
          )}
        />
        <span className="shrink-0">
          {tools.length > 0
            ? plural(tools.length, "step")
            : plural(thoughts, "thought")}
        </span>
        {shots > 0 && (
          <span className="flex shrink-0 items-center gap-1 font-normal text-ink-muted">
            <Icon name="image" className="size-3.5" />
            {shots}
          </span>
        )}
        <span className="flex-1" />
        <span className="mono-annotation text-ink-faint">
          {block.running ? (
            <Running since={block.started} />
          ) : (
            between(block.started, block.finished ?? block.started)
          )}
        </span>
        {block.running && !open && <LoadingMark />}
      </button>
      {open && (
        <ol className="border-t border-line">
          {block.steps.map((step) => (
            <StepRow
              key={step.key}
              step={step}
              check={check}
              flash={flashStep === step.key}
              open={shown.has(step.key)}
              onToggle={() => onShow(step.key)}
            />
          ))}
        </ol>
      )}
    </li>
  );
}

function Bubble({ who, children }: { who: ReactNode; children: ReactNode }) {
  return (
    <li className="flex max-w-[88%] shrink-0 flex-col items-end gap-1 self-end">
      <span className="text-right text-caption text-ink-muted">{who}</span>
      <div className="rounded-lg rounded-br-sm border border-line bg-field px-3 py-2 wrap-break-word whitespace-pre-wrap">
        {children}
      </div>
    </li>
  );
}

function AgentMessage({
  time,
  started,
  children,
}: {
  time: string;
  started: string;
  children: ReactNode;
}) {
  return (
    <li className="flex flex-col gap-1">
      <span className="flex items-center gap-1.5 text-caption text-ink-muted">
        <span aria-hidden className="size-1.5 bg-accent" />
        Reality Check
        <span className="mono-annotation text-ink-faint">
          {offset(started, time)}
        </span>
      </span>
      {children}
    </li>
  );
}

const ENDINGS: Record<
  string,
  { label: string; icon: "stop" | "warning" | null; danger: boolean }
> = {
  done: { label: "Finished", icon: null, danger: false },
  cancelled: { label: "Cancelled", icon: "stop", danger: false },
  "timed-out": { label: "Timed out", icon: "warning", danger: true },
  failed: { label: "Failed to run", icon: "warning", danger: true },
};

function Ended({
  block,
  started,
}: {
  block: Extract<Block, { kind: "ended" }>;
  started: string;
}) {
  const ending = ENDINGS[block.status] ?? ENDINGS.failed;
  return (
    <li className="flex flex-col gap-1">
      <span
        className={cn(
          "flex items-center gap-2 text-caption",
          ending.danger ? "text-danger" : "text-ink-muted",
        )}
      >
        <span aria-hidden className="h-px flex-1 bg-line" />
        {ending.icon && <Icon name={ending.icon} className="size-3.5" />}
        {ending.label} after {between(started, block.time)}
        <span aria-hidden className="h-px flex-1 bg-line" />
      </span>
      {block.status !== "done" && block.status !== "cancelled" && (
        <p className="text-center text-caption text-ink-muted">
          {block.text}
          {block.remedy && ` ${block.remedy}`}
        </p>
      )}
    </li>
  );
}

function who(origin: string | null, what: string): string {
  return origin && origin !== "unknown" ? `${what}, from ${origin}` : what;
}

/**
 * The check as a conversation: what it was asked, what its agent said, its steps folded between, any steering, and
 * how it ended.
 */
export function ActivityPanel({
  check,
  focus,
}: {
  check: Check | null;
  focus: ActivityFocus | null;
}) {
  const { focusReport } = useUi();
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  const [shown, setShown] = useState<ReadonlySet<string>>(new Set());
  const [flash, setFlash] = useState<string | null>(null);
  const running = check ? isRunning(check.state) : false;
  const entries = check?.activity?.entries;
  const blocks = useMemo(
    () => (entries ? blocksOf(entries, running) : []),
    [entries, running],
  );
  const list = useRef<HTMLOListElement>(null);
  const pinned = useRef(true);
  const [unseen, setUnseen] = useState(false);
  const steps = useMemo(() => toolSteps(blocks), [blocks]);
  const lastSteps = [...blocks]
    .reverse()
    .find((block) => block.kind === "steps")?.key;
  const [seenKey, setSeenKey] = useState(check?.key);
  if (seenKey !== check?.key) {
    setSeenKey(check?.key);
    setToggled({});
    setShown(new Set());
    setUnseen(false);
  }

  useEffect(() => {
    if (pinned.current && list.current) {
      list.current.scrollTop = list.current.scrollHeight;
    } else if (running) {
      const timer = setTimeout(() => setUnseen(true), 0);
      return () => clearTimeout(timer);
    }
  }, [entries?.length, running]);

  useEffect(() => {
    pinned.current = true;
    const frame = requestAnimationFrame(() => {
      if (list.current) {
        list.current.scrollTop = list.current.scrollHeight;
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [check?.key]);

  // Show in activity: open the step's block, scroll to it, and mark it for a moment.
  useEffect(() => {
    if (!focus || !check) {
      return;
    }
    const key =
      focus.step ??
      (focus.path
        ? stepFor(focus.path, check.evidence, steps)?.key
        : undefined);
    if (!key) {
      return;
    }
    const block = blocks.find(
      (each) =>
        each.kind === "steps" && each.steps.some((step) => step.key === key),
    );
    pinned.current = false;
    const start = setTimeout(() => {
      if (block) {
        setToggled((current) => ({ ...current, [block.key]: true }));
      }
      setFlash(key);
    }, 0);
    const frame = requestAnimationFrame(() =>
      requestAnimationFrame(() =>
        list.current
          ?.querySelector(`[data-step="${CSS.escape(key)}"]`)
          ?.scrollIntoView({ block: "center", behavior: "smooth" }),
      ),
    );
    const end = setTimeout(() => setFlash(null), 1800);
    return () => {
      clearTimeout(start);
      cancelAnimationFrame(frame);
      clearTimeout(end);
    };
    // Only a new request to show something moves it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.nonce]);

  if (!check) {
    return (
      <aside
        aria-label="Activity"
        className="grid h-full place-items-center bg-panel p-6 text-center text-ink-muted"
      >
        Pick a check to see what it did.
      </aside>
    );
  }

  const step = running ? currentStep(blocks) : null;
  const started = check.summary.started_at;

  return (
    <aside
      aria-label="Activity"
      className="flex h-full min-h-0 flex-col bg-panel"
    >
      <header className="flex h-9 shrink-0 items-center gap-2 border-b border-line pr-2 pl-3">
        <h2 className="text-label">Activity</h2>
        <span className="mono-annotation text-ink-muted">
          {plural(steps.length, "step")}
        </span>
      </header>
      <div className="relative flex min-h-0 flex-1 flex-col">
        <ol
          ref={list}
          onScroll={(event) => {
            const element = event.currentTarget;
            pinned.current =
              element.scrollHeight - element.scrollTop - element.clientHeight <
              PINNED_PX;
            if (pinned.current) {
              setUnseen(false);
            }
          }}
          className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 pt-4 pb-6"
        >
          {check.activityError !== null && (
            <li>
              <ErrorNotice
                error={check.activityError}
                title="Could not read the activity."
              />
            </li>
          )}
          {!check.activity && check.activityError === null && (
            <li className="flex flex-col items-center gap-2 py-10 text-ink-muted">
              <LoadingMark size={12} />
              Reading the activity
            </li>
          )}
          {check.activity && blocks.length === 0 && (
            <li className="flex flex-col items-center gap-2 py-10 text-ink-muted">
              {running && <LoadingMark size={12} />}
              {running ? "Starting the agent" : "Nothing was recorded."}
            </li>
          )}
          {blocks.map((block) => {
            switch (block.kind) {
              case "request":
                return (
                  <Bubble key={block.key} who={who(block.origin, "Request")}>
                    {block.text}
                  </Bubble>
                );
              case "steered":
                return (
                  <Bubble
                    key={block.key}
                    who={
                      <>
                        {who(block.origin, "Steering")},{" "}
                        {block.data.error ? "not delivered" : "delivered"}{" "}
                        <span className="mono-annotation text-ink-faint">
                          {offset(started, block.time)}
                        </span>
                      </>
                    }
                  >
                    {block.text}
                  </Bubble>
                );
              case "said":
                return (
                  <AgentMessage
                    key={block.key}
                    time={block.time}
                    started={started}
                  >
                    {block.text.trimStart().startsWith("# ") ? (
                      <div className="flex flex-col items-start gap-2">
                        <p>The agent wrote its report.</p>
                        <button
                          type="button"
                          onClick={focusReport}
                          className="inline-flex h-7 items-center gap-1.5 rounded-md border border-accent-ink bg-accent-soft px-2.5 text-label text-ink hover:brightness-97"
                        >
                          <Icon name="file" />
                          Read the report
                          <Icon name="arrow-right" />
                        </button>
                      </div>
                    ) : (
                      <Markdown>{block.text}</Markdown>
                    )}
                  </AgentMessage>
                );
              case "steps": {
                const open =
                  toggled[block.key] ??
                  (block.running || (running && block.key === lastSteps));
                return (
                  <StepBlock
                    key={block.key}
                    block={block}
                    check={check}
                    open={open}
                    flashStep={flash}
                    shown={shown}
                    onShow={(key) =>
                      setShown((keys) => {
                        const next = new Set(keys);
                        if (!next.delete(key)) {
                          next.add(key);
                        }
                        return next;
                      })
                    }
                    onToggle={() =>
                      setToggled((current) => ({
                        ...current,
                        [block.key]: !open,
                      }))
                    }
                  />
                );
              }
              case "ended":
                return (
                  <Ended key={block.key} block={block} started={started} />
                );
            }
          })}
        </ol>
        {unseen && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              list.current?.scrollTo({
                top: list.current.scrollHeight,
                behavior: "smooth",
              })
            }
            className="absolute bottom-3 left-1/2 -translate-x-1/2 shadow-popover"
          >
            <Icon name="arrow-down" />
            Jump to latest
          </Button>
        )}
      </div>
      {running && (
        <div className="relative flex shrink-0 items-center gap-2 border-t border-line bg-accent-soft py-1.5 pr-1.5 pl-3">
          <ProgressBar className="-top-px" />
          <LoadingMark size={12} />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="flex items-center gap-1.5 text-label">
              Checking
              <Elapsed
                check={{
                  state: check.state,
                  started_at: started,
                  ended_at: null,
                }}
                className="text-ink"
              />
            </span>
            {step && (
              <span
                className="truncate mono-annotation text-ink-muted"
                title={step.target}
              >
                Step {step.count}, {step.verb.toLowerCase()} {step.target}
              </span>
            )}
          </span>
        </div>
      )}
    </aside>
  );
}
