import { useEffect, useRef, useState } from "react";

import { ActivityPanel, type ActivityFocus } from "@/components/ActivityPanel";
import { ReportCanvas } from "@/components/canvas/ReportCanvas";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ErrorNotice } from "@/components/ErrorNotice";
import { ShortcutsDialog } from "@/components/ShortcutsDialog";
import { Sidebar } from "@/components/Sidebar";
import { StatusBar } from "@/components/StatusBar";
import { TopBar, type NarrowPane, type Pane } from "@/components/TopBar";
import { EmptyState } from "@/components/ui/empty-state";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Workspace } from "@/components/Workspace";
import type { CheckReference } from "@/lib/api";
import { onDisplay, requestDisplayMode } from "@/lib/host";
import {
  clearLayout,
  DEFAULT_LAYOUT,
  loadLayout,
  saveLayout,
  useBreakpoint,
  useWidth,
  type AppLayout,
} from "@/lib/layout";
import {
  back,
  forward,
  pageOf,
  push,
  replace,
  START,
  type Nav,
  type Route,
} from "@/lib/nav";
import { useShortcuts } from "@/lib/shortcuts";
import { isRunning, select, useStore } from "@/lib/store";
import { UiContext, type Ui } from "@/lib/ui";
import { cn } from "@/lib/utils";

function Toast({ text }: { text: string | null }) {
  return (
    <div
      role="status"
      className={cn(
        "pointer-events-none fixed bottom-10 left-1/2 z-60 max-w-[calc(100vw-32px)] -translate-x-1/2 rounded-md bg-raised px-3 py-2 text-label shadow-popover transition-opacity",
        text ? "opacity-100" : "opacity-0",
      )}
    >
      {text}
    </div>
  );
}

// Medium widths start without the checks sidebar, unless the person has set the panes up themselves.
function startingLayout(width: number): AppLayout {
  return width < 1080
    ? { ...DEFAULT_LAYOUT, sidebar: { ...DEFAULT_LAYOUT.sidebar, open: false } }
    : DEFAULT_LAYOUT;
}

function App() {
  const store = useStore();
  const check = store.check;
  const [root, breakpoint] = useBreakpoint();
  const [scope, setScope] = useState<string | null>(null);
  const [navs, setNavs] = useState<Record<string, Nav>>({});
  const [focus, setFocus] = useState<ActivityFocus | null>(null);
  const [canvasFlash, setCanvasFlash] = useState(0);
  const [shortcuts, setShortcuts] = useState(false);
  const [narrowPane, setNarrowPane] = useState<NarrowPane>("report");
  const [display, setDisplay] = useState({
    fullscreen: false,
    expandable: false,
  });
  const width = useWidth();
  const [layout, setLayoutState] = useState<AppLayout>(
    () => loadLayout() ?? startingLayout(width),
  );
  const [layoutKey, setLayoutKey] = useState(0);
  const [toastText, setToastText] = useState<string | null>(null);
  const [opened, setOpened] = useState<string | null>(null);

  useEffect(
    () =>
      onDisplay(({ mode, available }) =>
        setDisplay({
          fullscreen: mode === "fullscreen",
          expandable: mode !== "fullscreen" && available.includes("fullscreen"),
        }),
      ),
    [],
  );

  const nav = (check && navs[check.key]) || START;
  const fileOpen = nav.current.kind === "file";
  // What opened the viewer, so closing it puts focus back there rather than on the page.
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!fileOpen && opener.current) {
      const element = opener.current;
      opener.current = null;
      if (element.isConnected) {
        element.focus();
      }
    }
  }, [fileOpen]);

  const toast = (text: string) => {
    setToastText(text);
    setTimeout(() => setToastText(null), 2200);
  };

  const setNav = (change: (nav: Nav) => Nav) => {
    if (check) {
      setNavs((current) => ({
        ...current,
        [check.key]: change(current[check.key] ?? START),
      }));
    }
  };

  const setLayout = (next: AppLayout, remount: boolean) => {
    setLayoutState(next);
    saveLayout(next);
    if (remount) {
      setLayoutKey((count) => count + 1);
    }
  };

  const togglePane = (pane: Pane, open?: boolean) => {
    const next = open ?? !layout[pane].open;
    if (next !== layout[pane].open) {
      setLayout({ ...layout, [pane]: { ...layout[pane], open: next } }, true);
    }
  };

  // A running check is about what it is doing, so its Activity opens when it is first shown.
  if (check && check.key !== opened && check.detail) {
    setOpened(check.key);
    if (
      isRunning(check.state) &&
      breakpoint !== "narrow" &&
      !layout.activity.open
    ) {
      setLayoutState({
        ...layout,
        activity: { ...layout.activity, open: true },
      });
      setLayoutKey((count) => count + 1);
    }
  }

  const selectCheck = (ref: CheckReference) => {
    select(ref);
    if (breakpoint === "narrow") {
      setNarrowPane("report");
    }
  };

  const ui: Ui = {
    check,
    nav,
    navigate: (route: Route) => {
      setNav((current) => push(current, route));
      if (breakpoint === "narrow") {
        setNarrowPane("report");
      }
    },
    replaceRoute: (route: Route) =>
      setNav((current) => replace(current, route)),
    goBack: () => setNav(back),
    goForward: () => setNav(forward),
    openEvidence: (path, list) => {
      if (!check?.evidence.some((item) => item.path === path)) {
        toast("That file is not in this check's evidence folder.");
        return;
      }
      if (!fileOpen && document.activeElement instanceof HTMLElement) {
        opener.current = document.activeElement;
      }
      setNav((current) =>
        push(current, {
          kind: "file",
          path,
          list: list ?? [],
          from: pageOf(current.current),
        }),
      );
      if (breakpoint === "narrow") {
        setNarrowPane("report");
      }
    },
    showInActivity: (target) => {
      setFocus({ ...target, nonce: Date.now() });
      if (breakpoint === "narrow") {
        setNarrowPane("activity");
      } else {
        togglePane("activity", true);
      }
    },
    focusReport: () => {
      setNav((current) => push(current, { kind: "report" }));
      setCanvasFlash((count) => count + 1);
      if (breakpoint === "narrow") {
        setNarrowPane("report");
      }
    },
    selectCheck,
    toast,
  };

  const projects = scope
    ? store.projects.filter((project) => project.checks_directory === scope)
    : store.projects;
  const visible = projects.flatMap((project) => project.checks);

  const step = (offset: number) => {
    const index = check
      ? visible.findIndex(
          (summary) =>
            summary.check_id === check.id &&
            summary.project.checks_directory === check.ref.checks_directory,
        )
      : -1;
    const next = visible[index + offset];
    if (next) {
      selectCheck({
        check_id: next.check_id,
        checks_directory: next.project.checks_directory,
      });
    }
  };

  useShortcuts({
    "[": () => breakpoint !== "narrow" && togglePane("sidebar"),
    "]": () => breakpoint !== "narrow" && togglePane("activity"),
    j: () => step(1),
    k: () => step(-1),
    e: () => check && ui.navigate({ kind: "evidence" }),
    escape: ui.goBack,
    backspace: ui.goBack,
    "?": () => setShortcuts(true),
  });

  const height = display.fullscreen ? "h-dvh" : "h-[600px]";

  if (store.phase !== "ready") {
    return (
      <div
        className={cn("grid place-items-center bg-canvas p-6 text-ink", height)}
      >
        {store.phase === "error" ? (
          <ErrorNotice
            error={store.error}
            title="Could not read the checks."
            className="max-w-120"
          />
        ) : (
          <EmptyState
            tile={<LoadingMark size={24} />}
            tileClassName="bg-pastel-rose"
            title="Reading your checks"
            className="w-full max-w-110 rounded-lg"
          >
            Every check on this machine, from every project checks were started
            from.
          </EmptyState>
        )}
      </div>
    );
  }

  const changeScope = (next: string | null) => {
    setScope(next);
    if (next && check && check.ref.checks_directory !== next) {
      const newest = store.projects.find(
        (project) => project.checks_directory === next,
      )?.checks[0];
      if (newest) {
        select({ check_id: newest.check_id, checks_directory: next });
      }
    }
  };

  const sidebar = (
    <Sidebar
      projects={store.projects}
      scope={scope}
      onScope={changeScope}
      selected={store.selected}
      onSelect={selectCheck}
      error={store.listError}
    />
  );
  const activity = <ActivityPanel check={check} focus={focus} />;
  const canvas = (
    <ReportCanvas
      check={check}
      empty={store.checks.length === 0}
      flash={canvasFlash}
    />
  );

  return (
    <UiContext.Provider value={ui}>
      <div
        ref={root}
        className={cn(
          "flex flex-col overflow-hidden bg-canvas text-ink",
          height,
        )}
      >
        <TopBar
          breakpoint={breakpoint}
          check={check}
          panes={{
            sidebar: layout.sidebar.open,
            activity: layout.activity.open,
          }}
          onTogglePane={togglePane}
          narrowPane={narrowPane}
          onNarrowPane={setNarrowPane}
          onScope={(directory) => changeScope(directory)}
          onExpand={
            display.expandable
              ? () => void requestDisplayMode("fullscreen")
              : undefined
          }
          settings={{
            onShortcuts: () => setShortcuts(true),
            onResetLayout: () => {
              clearLayout();
              setLayout(startingLayout(width), true);
              toast("Layout reset");
            },
          }}
        />
        <main className="flex min-h-0 flex-1">
          <ErrorBoundary what="The workspace" className="m-4 flex-1">
            {breakpoint === "narrow" ? (
              <div className="flex min-w-0 flex-1 flex-col">
                {narrowPane === "checks"
                  ? sidebar
                  : narrowPane === "report"
                    ? canvas
                    : activity}
              </div>
            ) : (
              <Workspace
                key={`${breakpoint}-${layoutKey}`}
                layout={layout}
                width={width}
                sidebar={sidebar}
                canvas={canvas}
                activity={activity}
                onResized={(widths) =>
                  setLayout(
                    {
                      sidebar: widths.sidebar
                        ? { open: true, size: widths.sidebar }
                        : layout.sidebar,
                      activity: widths.activity
                        ? { open: true, size: widths.activity }
                        : layout.activity,
                    },
                    false,
                  )
                }
              />
            )}
          </ErrorBoundary>
        </main>
        {breakpoint === "wide" && <StatusBar check={check} />}
        <ShortcutsDialog open={shortcuts} onOpenChange={setShortcuts} />
        <Toast text={toastText} />
      </div>
    </UiContext.Provider>
  );
}

export default App;
