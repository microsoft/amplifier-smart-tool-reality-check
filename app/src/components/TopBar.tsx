import { SettingsMenu } from "@/components/SettingsMenu";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Segmented } from "@/components/ui/segmented";
import { StatusMark } from "@/components/ui/status-mark";
import { Tooltip } from "@/components/ui/tooltip";
import { AppMark, Wordmark } from "@/components/Wordmark";
import type { Breakpoint } from "@/lib/layout";
import { isRunning, type Check } from "@/lib/store";

export type Pane = "sidebar" | "activity";
export type NarrowPane = "checks" | "activity" | "report";

/** Shows or hides a side pane. Activity also says its name, and shows when its check is running. */
function PaneToggle({
  pane,
  open,
  onToggle,
  check,
}: {
  pane: Pane;
  open: boolean;
  onToggle: (pane: Pane) => void;
  check?: Check | null;
}) {
  const label = pane === "sidebar" ? "Checks" : "Activity";
  const running = pane === "activity" && check && isRunning(check.state);
  return (
    <Tooltip
      content={`${open ? "Hide" : "Show"} ${label.toLowerCase()}`}
      keys={pane === "sidebar" ? "[" : "]"}
    >
      <Button
        size="sm"
        icon={pane === "sidebar"}
        aria-label={label}
        aria-pressed={open}
        onClick={() => onToggle(pane)}
        className="shrink-0 aria-pressed:bg-hover"
      >
        <Icon name={pane === "sidebar" ? "sidebar-left" : "sidebar-right"} />
        {pane === "activity" && (
          <>
            <span>Activity</span>
            {running && <LoadingMark />}
          </>
        )}
      </Button>
    </Tooltip>
  );
}

/** The bar along the top: the brand, which check is shown and how it ran, then settings and the side panes. */
export function TopBar({
  breakpoint,
  check,
  panes,
  onTogglePane,
  narrowPane,
  onNarrowPane,
  onScope,
  onExpand,
  settings,
}: {
  breakpoint: Breakpoint;
  check: Check | null;
  panes: Record<Pane, boolean>;
  onTogglePane: (pane: Pane) => void;
  narrowPane: NarrowPane;
  onNarrowPane: (pane: NarrowPane) => void;
  onScope: (checksDirectory: string) => void;
  /** Asks the host for fullscreen; absent when the view is fullscreen already, or the host has no such mode. */
  onExpand?: () => void;
  settings: Parameters<typeof SettingsMenu>[0];
}) {
  const narrow = breakpoint === "narrow";
  return (
    <header className="flex h-11 shrink-0 items-center gap-2 border-b border-line bg-panel px-2">
      {!narrow && (
        <PaneToggle
          pane="sidebar"
          open={panes.sidebar}
          onToggle={onTogglePane}
        />
      )}
      {narrow ? (
        <AppMark />
      ) : (
        <h1 className="flex shrink-0 items-center">
          <Wordmark />
        </h1>
      )}
      {!narrow && (
        <span aria-hidden className="mx-1.5 h-5 w-px shrink-0 bg-line" />
      )}
      {!narrow && check && (
        <nav
          aria-label="Where you are"
          className="flex min-w-0 flex-1 items-center gap-1.5"
        >
          {check.project && (
            <>
              <button
                type="button"
                onClick={() =>
                  check.project && onScope(check.project.checks_directory)
                }
                title={`Show only this project: ${check.project.root}`}
                className="shrink-0 rounded-sm px-1 text-ink-muted hover:bg-hover hover:text-ink"
              >
                {check.project.name}
              </button>
              <span aria-hidden className="text-ink-faint">
                /
              </span>
            </>
          )}
          <span
            className="min-w-0 truncate font-medium"
            title={check.summary.request}
          >
            {check.label}
          </span>
          <StatusMark
            check={{
              state: check.state,
              started_at: check.summary.started_at,
              ended_at: check.record?.ended_at ?? check.summary.ended_at,
            }}
            showElapsed={isRunning(check.state)}
            className="ml-1 text-ink-muted"
          />
        </nav>
      )}
      {narrow ? (
        <Segmented
          label="Show"
          size="sm"
          value={narrowPane}
          onChange={onNarrowPane}
          options={[
            { value: "checks", label: "Checks" },
            { value: "report", label: "Report" },
            { value: "activity", label: "Activity" },
          ]}
          className="mx-auto"
        />
      ) : (
        !check && <span className="flex-1" />
      )}
      <span className="flex shrink-0 items-center gap-1">
        {onExpand && (
          <Tooltip content="Full screen">
            <Button size="sm" icon aria-label="Full screen" onClick={onExpand}>
              <Icon name="expand" />
            </Button>
          </Tooltip>
        )}
        <SettingsMenu {...settings} />
        {!narrow && (
          <>
            <span aria-hidden className="mx-1 h-5 w-px bg-line" />
            <PaneToggle
              pane="activity"
              open={panes.activity}
              onToggle={onTogglePane}
              check={check}
            />
          </>
        )}
      </span>
    </header>
  );
}
