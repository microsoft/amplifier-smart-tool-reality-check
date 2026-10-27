import { useCallback, useEffect, useState } from "react";

/** How much room there is: all three panes, the list and the center, or one pane at a time. */
export type Breakpoint = "wide" | "medium" | "narrow";

export function breakpointOf(width: number): Breakpoint {
  if (width >= 1080) {
    return "wide";
  }
  return width >= 900 ? "medium" : "narrow";
}

export function useBreakpoint(): [
  (element: HTMLElement | null) => void,
  Breakpoint,
] {
  const [width, setWidth] = useState(() => window.innerWidth);
  const ref = useCallback((element: HTMLElement | null) => {
    if (!element) {
      return;
    }
    const observer = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, breakpointOf(width)];
}

/** The window's width, kept up to date. */
export function useWidth(): number {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return width;
}

export type PaneLayout = { open: boolean; size: number };
export type AppLayout = { sidebar: PaneLayout; activity: PaneLayout };

const STORAGE_NAME = "reality-check.layout";
export const DEFAULT_LAYOUT: AppLayout = {
  sidebar: { open: true, size: 240 },
  // Activity starts closed; the top bar's Activity button and ] open it.
  activity: { open: false, size: 400 },
};

/** The panes as the person left them, from local storage; a fresh one gets the defaults. */
export function loadLayout(): AppLayout | null {
  try {
    const saved = JSON.parse(
      localStorage.getItem(STORAGE_NAME) ?? "null",
    ) as AppLayout | null;
    return saved && saved.sidebar && saved.activity ? saved : null;
  } catch {
    return null;
  }
}

export function saveLayout(layout: AppLayout) {
  try {
    localStorage.setItem(STORAGE_NAME, JSON.stringify(layout));
  } catch {
    // A host that blocks storage keeps the layout until the view reloads.
  }
}

export function clearLayout() {
  try {
    localStorage.removeItem(STORAGE_NAME);
  } catch {
    // Nothing was kept to clear.
  }
}
