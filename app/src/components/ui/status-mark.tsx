import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import type { CheckState } from "@/lib/api";
import { elapsedSeconds, isRunning } from "@/lib/store";
import { duration, useNow } from "@/lib/time";
import { cn } from "@/lib/utils";

/** How a check ran, in words that never say what it found: only its report says what passed. */
export const STATE_LABELS: Record<CheckState, string> = {
  running: "Running",
  done: "Finished",
  cancelled: "Cancelled",
  "timed-out": "Timed out",
  crashed: "Crashed",
  failed: "Failed to run",
};

/** What each way of ending means, for tooltips. */
export const STATE_NOTES: Record<CheckState, string> = {
  running: "The check is still going.",
  done: "The check ran to its end. Its report says what passed and what did not.",
  cancelled: "The check was cancelled before it ended.",
  "timed-out": "The check ran out of time and was stopped.",
  crashed: "The process running the check stopped without ending it.",
  failed: "The check could not run to its end.",
};

type Timed = { state: CheckState; started_at: string; ended_at: string | null };

/** A check's elapsed time, counting up while it runs. */
export function Elapsed({
  check,
  className,
}: {
  check: Timed;
  className?: string;
}) {
  const now = useNow(isRunning(check.state));
  return (
    <span className={cn("mono-annotation tabular-nums", className)}>
      {duration(elapsedSeconds(check, now))}
    </span>
  );
}

/** Whether the state is a problem with how the check ran, which only the danger hue marks. */
export function troubled(state: CheckState): boolean {
  return state === "crashed" || state === "failed" || state === "timed-out";
}

/**
 * How a check ran: running with its elapsed time, finished in neutral ink, problems in danger. Finished is never a
 * pass, so it has no check mark.
 */
export function StatusMark({
  check,
  showElapsed = true,
  className,
}: {
  check: Timed;
  showElapsed?: boolean;
  className?: string;
}) {
  const state = check.state;
  return (
    <span
      title={STATE_NOTES[state]}
      className={cn(
        "inline-flex min-w-0 shrink-0 items-center gap-1.5 text-label whitespace-nowrap",
        troubled(state) && "text-danger",
        state === "cancelled" && "text-ink-muted",
        className,
      )}
    >
      {state === "running" && <LoadingMark />}
      {state === "done" && (
        <span aria-hidden className="size-2 shrink-0 border border-ink-muted" />
      )}
      {troubled(state) && <Icon name="warning" />}
      {state === "cancelled" && <Icon name="stop" />}
      {STATE_LABELS[state]}
      {showElapsed && (
        <Elapsed
          check={check}
          className={troubled(state) ? "text-danger" : "text-ink-muted"}
        />
      )}
    </span>
  );
}
