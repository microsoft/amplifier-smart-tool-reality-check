import { useEffect, useState } from "react";

import { ActivityPanel, type ActivityFocus } from "@/components/ActivityPanel";
import { EvidenceViewer } from "@/components/canvas/EvidenceViewer";
import { ReportMarkdown } from "@/components/canvas/ReportPage";
import { ErrorNotice } from "@/components/ErrorNotice";
import { EvidenceThumb } from "@/components/EvidenceThumb";
import { Icon, type IconName } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Segmented } from "@/components/ui/segmented";
import { StatusMark } from "@/components/ui/status-mark";
import { onOpened } from "@/lib/host";
import { useBreakpoint } from "@/lib/layout";
import { START, type Nav, type Route } from "@/lib/nav";
import { useShortcuts } from "@/lib/shortcuts";
import { select, useStore, type Check } from "@/lib/store";
import { dateTime } from "@/lib/time";
import { UiContext, type Ui } from "@/lib/ui";
import { cn } from "@/lib/utils";

import type { Gallery as Shots, Outcome } from "./content";

// Sizes the app's own classes do not have are styles, not classes: the app's build scans this folder too, and would
// gain the classes.

type Pane = "report" | "activity";
type File = { path: string; list: string[] };

// The app's own words for how each thing checked came out.
const OUTCOMES: Record<
  Outcome,
  { word: string; icon: IconName | null; className: string }
> = {
  passed: { word: "Passed", icon: "check", className: "text-ink-muted" },
  failed: { word: "Failed", icon: "close", className: "text-danger" },
  skipped: {
    word: "Not checked",
    icon: null,
    className: "text-ink-faint",
  },
};

/** A row of the screenshots behind each result, which scrolls sideways when it does not fit. */
function Gallery({
  check,
  gallery,
  onOpen,
}: {
  check: Check;
  gallery: Shots;
  onOpen: (path: string, list: string[]) => void;
}) {
  const shown = gallery.items.flatMap((each) => {
    const path = `evidence/${each.evidence}`;
    const item = check.evidence.find((item) => item.path === path);
    return item ? [{ ...each, path, item }] : [];
  });
  if (shown.length === 0) {
    return null;
  }
  const paths = shown.map((each) => each.path);
  return (
    <section
      aria-label={gallery.title}
      className="flex flex-col gap-2.5"
      style={{ marginTop: 32 }}
    >
      <h2 className="flex items-baseline gap-2 text-label">
        {gallery.title}
        <span className="mono-annotation text-ink-muted">{shown.length}</span>
      </h2>
      <ul className="flex gap-3 overflow-x-auto" style={{ paddingBottom: 8 }}>
        {shown.map(({ item, label, outcome }) => {
          const { word, icon, className } = OUTCOMES[outcome];
          return (
            <li
              key={item.path}
              className="flex shrink-0 flex-col gap-1"
              style={{ width: 180 }}
            >
              <EvidenceThumb
                checkRef={check.ref}
                item={item}
                caption={false}
                className="w-full"
                onOpen={() => onOpen(item.path, paths)}
              />
              <span className="text-label">{label}</span>
              <span
                className={cn(
                  "flex items-center gap-1 text-caption",
                  className,
                )}
              >
                {icon && <Icon name={icon} className="size-3.5" />}
                {word}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** The report of one check, with an evidence file opened over it. */
function Report({
  check,
  file,
  onFile,
  onClose,
  onShowInActivity,
  onOpen,
  gallery,
  toast,
}: {
  check: Check;
  gallery: Shots | null;
  file: File | null;
  onFile: (file: File) => void;
  onOpen: (path: string, list: string[]) => void;
  onClose: () => void;
  onShowInActivity: (path: string) => void;
  toast: (text: string) => void;
}) {
  return (
    <section
      aria-label="Report"
      className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-canvas"
    >
      <header className="flex h-9 shrink-0 items-center gap-3 border-b border-line bg-panel pr-2 pl-3">
        <h2 className="text-label">Report</h2>
        <StatusMark
          check={{
            state: check.state,
            started_at: check.summary.started_at,
            ended_at: check.record?.ended_at ?? check.summary.ended_at,
          }}
          className="text-ink-muted"
        />
        <span className="mono-annotation text-ink-muted">
          {dateTime(check.summary.started_at)}
        </span>
      </header>
      <div className="relative min-h-0 flex-1">
        <div className="absolute inset-0 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1280px] px-8 pt-7 pb-20 max-sm:px-4">
            <article className="example-report max-w-[880px] min-w-0">
              {check.report && (
                <ReportMarkdown check={check}>{check.report}</ReportMarkdown>
              )}
              {gallery && (
                <Gallery check={check} gallery={gallery} onOpen={onOpen} />
              )}
            </article>
          </div>
        </div>
        {file && (
          <EvidenceViewer
            key={check.key}
            check={check}
            state={file}
            onChange={onFile}
            onClose={onClose}
            onShowInActivity={onShowInActivity}
            toast={toast}
          />
        )}
      </div>
    </section>
  );
}

/** One check in the app's own report, activity, and evidence viewer: the example on the tool's website. */
export default function Example() {
  const store = useStore();
  const check = store.check;
  const [root, breakpoint] = useBreakpoint();
  const narrow = breakpoint === "narrow";
  const [pane, setPane] = useState<Pane>("report");
  const [file, setFile] = useState<File | null>(null);
  const [focus, setFocus] = useState<ActivityFocus | null>(null);
  const [toastText, setToastText] = useState<string | null>(null);
  const [gallery, setGallery] = useState<Shots | null>(null);

  // The host sends the gallery with what opened the app.
  useEffect(
    () =>
      onOpened((opened) => {
        const sent = (opened as { gallery?: Shots }).gallery;
        setGallery(sent ?? null);
      }),
    [],
  );

  const nav: Nav = file
    ? {
        back: [],
        current: { kind: "file", ...file, from: { kind: "report" } },
        forward: [],
      }
    : START;
  const go = (route: Route) => {
    setFile(
      route.kind === "file" ? { path: route.path, list: route.list } : null,
    );
    setPane("report");
  };
  const toast = (text: string) => {
    setToastText(text);
    setTimeout(() => setToastText(null), 2200);
  };
  const ui: Ui = {
    check,
    nav,
    navigate: go,
    replaceRoute: go,
    goBack: () => setFile(null),
    goForward: () => {},
    openEvidence: (path, list) => {
      if (!check?.evidence.some((item) => item.path === path)) {
        toast("That file is not in this check's evidence folder.");
        return;
      }
      setFile({ path, list: list ?? [] });
      setPane("report");
    },
    showInActivity: (target) => {
      setFocus({ ...target, nonce: Date.now() });
      if (narrow) {
        setPane("activity");
      }
    },
    focusReport: () => go({ kind: "report" }),
    selectCheck: select,
    toast,
  };

  useShortcuts({ escape: ui.goBack });

  if (store.phase !== "ready" || !check) {
    return (
      <div className="grid h-dvh place-items-center bg-canvas p-6 text-ink">
        {store.phase === "error" ? (
          <ErrorNotice
            error={store.error}
            title="Could not read the check."
            className="max-w-120"
          />
        ) : (
          <LoadingMark size={24} />
        )}
      </div>
    );
  }

  const report = (
    <Report
      check={check}
      file={file}
      onFile={setFile}
      onClose={ui.goBack}
      onShowInActivity={(path) => ui.showInActivity({ path })}
      onOpen={ui.openEvidence}
      gallery={gallery}
      toast={toast}
    />
  );
  const activity = <ActivityPanel check={check} focus={focus} />;

  return (
    <UiContext.Provider value={ui}>
      <div
        ref={root}
        className={cn(
          "flex h-dvh overflow-hidden bg-canvas text-ink",
          narrow && "flex-col",
        )}
      >
        {narrow ? (
          <>
            <div className="flex h-10 shrink-0 items-center justify-center border-b border-line bg-panel px-2">
              <Segmented
                label="Show"
                size="sm"
                value={pane}
                onChange={setPane}
                options={[
                  { value: "report", label: "Report" },
                  { value: "activity", label: "Activity" },
                ]}
              />
            </div>
            <div className="flex min-h-0 flex-1 flex-col">
              {pane === "report" ? report : activity}
            </div>
          </>
        ) : (
          <>
            {report}
            <div
              className="shrink-0 border-l border-line"
              style={{ width: 380 }}
            >
              {activity}
            </div>
          </>
        )}
        <div
          role="status"
          className={cn(
            "pointer-events-none fixed bottom-10 left-1/2 z-60 max-w-[calc(100vw-32px)] -translate-x-1/2 rounded-md bg-raised px-3 py-2 text-label shadow-popover transition-opacity",
            toastText ? "opacity-100" : "opacity-0",
          )}
        >
          {toastText}
        </div>
      </div>
    </UiContext.Provider>
  );
}
