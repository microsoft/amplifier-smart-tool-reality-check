import { useSyncExternalStore } from "react";

const clock = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const clockSeconds = new Intl.DateTimeFormat("en", {
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

/** A span of seconds, such as "45s", "3m 5s", or "1h 2m". */
export function duration(total: number): string {
  const seconds = Math.round(total);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return minutes > 0 ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}

/** The span between two times, to a tenth of a second under ten seconds. */
export function between(from: string, to: string | number): string {
  const end = typeof to === "number" ? to : Date.parse(to);
  const seconds = Math.max(0, (end - Date.parse(from)) / 1000);
  if (seconds < 0.05) {
    return "<0.1s";
  }
  return seconds < 10 ? `${seconds.toFixed(1)}s` : duration(seconds);
}

/** An offset from a check's start, as a clock: "+0:34", "+12:05". */
export function offset(from: string, to: string): string {
  const seconds = Math.max(
    0,
    Math.round((Date.parse(to) - Date.parse(from)) / 1000),
  );
  const minutes = Math.floor(seconds / 60);
  return `+${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

export function dateTime(iso: string): string {
  return clock.format(Date.parse(iso));
}

export function timeOfDay(iso: string): string {
  return clockSeconds.format(Date.parse(iso));
}

const TICK_MS = 1000;
let now = Date.now();
let timer: ReturnType<typeof setInterval> | undefined;
const listeners = new Set<() => void>();

// One clock for every ticking reader, so two elapsed times on screen never differ, and one that starts ticking late
// reads the current time rather than when it mounted.
function subscribeClock(listener: () => void): () => void {
  listeners.add(listener);
  if (timer === undefined) {
    now = Date.now();
    timer = setInterval(() => {
      now = Date.now();
      listeners.forEach((each) => each());
    }, TICK_MS);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      clearInterval(timer);
      timer = undefined;
    }
  };
}

function subscribeNever(): () => void {
  return () => {};
}

/** Now, ticking every second while `ticking`. */
export function useNow(ticking = true): number {
  return useSyncExternalStore(
    ticking ? subscribeClock : subscribeNever,
    () => now,
  );
}
