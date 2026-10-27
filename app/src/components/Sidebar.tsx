import { useState } from "react";

import { ErrorNotice } from "@/components/ErrorNotice";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import {
  Menu,
  MenuContent,
  MenuGroupLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import {
  Elapsed,
  STATE_LABELS,
  STATE_NOTES,
  troubled,
} from "@/components/ui/status-mark";
import { Tooltip } from "@/components/ui/tooltip";
import type { CheckReference, CheckSummary } from "@/lib/api";
import { shortPath } from "@/lib/format";
import { labelOf, type ProjectGroup } from "@/lib/store";
import { dateTime, duration } from "@/lib/time";
import { cn } from "@/lib/utils";

function refOf(summary: CheckSummary): CheckReference {
  return {
    check_id: summary.check_id,
    checks_directory: summary.project.checks_directory,
  };
}

/** How a check ran, compact: running with its time, finished with how long it took, else how it stopped. */
function CheckState({ summary }: { summary: CheckSummary }) {
  if (summary.state === "running") {
    return (
      <span
        title={STATE_NOTES.running}
        className="flex shrink-0 items-center gap-1.5 text-ink-muted"
      >
        <LoadingMark />
        <Elapsed check={summary} />
      </span>
    );
  }
  if (summary.state === "done") {
    return (
      <span
        title={`${STATE_LABELS.done}. ${STATE_NOTES.done}`}
        className="shrink-0 mono-annotation text-ink-faint"
      >
        {summary.ended_at &&
          duration(
            (Date.parse(summary.ended_at) - Date.parse(summary.started_at)) /
              1000,
          )}
      </span>
    );
  }
  return (
    <span
      title={STATE_NOTES[summary.state]}
      className={cn(
        "shrink-0 text-caption",
        troubled(summary.state) ? "text-danger" : "text-ink-muted",
      )}
    >
      {STATE_LABELS[summary.state]}
    </span>
  );
}

function CheckRow({
  summary,
  selected,
  indent,
  onSelect,
}: {
  summary: CheckSummary;
  selected: boolean;
  indent: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        title={summary.request}
        className={cn(
          "group/run relative flex w-full min-w-0 items-start gap-2 rounded-sm py-1.5 pr-2 text-left -outline-offset-2",
          indent ? "pl-7" : "pl-2.5",
          selected ? "bg-accent-soft" : "hover:bg-hover",
        )}
      >
        {selected && (
          <span
            aria-hidden
            className="absolute inset-y-1.5 left-0 w-0.5 bg-accent-ink"
          />
        )}
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="line-clamp-2 leading-4.5">
            {labelOf(summary.request)}
          </span>
          <span className="mono-annotation text-ink-muted">
            {dateTime(summary.started_at)}
          </span>
        </span>
        <span className="mt-0.5">
          <CheckState summary={summary} />
        </span>
      </button>
    </li>
  );
}

function ProjectTree({
  project,
  selected,
  onSelect,
}: {
  project: ProjectGroup;
  selected: string | null;
  onSelect: (ref: CheckReference) => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <li className="flex flex-col">
      <Tooltip
        content={<span className="mono-annotation">{project.root}</span>}
        side="right"
      >
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="flex h-7 w-full min-w-0 items-center gap-1.5 rounded-sm px-1.5 text-left text-label -outline-offset-2 hover:bg-hover"
        >
          <Icon
            name="chevron"
            className={cn(
              "shrink-0 text-ink-muted transition-transform",
              !open && "-rotate-90",
            )}
          />
          <span className="min-w-0 flex-1 truncate">{project.name}</span>
        </button>
      </Tooltip>
      {open && (
        <ol className="flex flex-col gap-px pb-1.5">
          {project.checks.map((summary) => (
            <CheckRow
              key={summary.check_id}
              summary={summary}
              indent
              selected={summary.check_id === selected}
              onSelect={() => onSelect(refOf(summary))}
            />
          ))}
        </ol>
      )}
    </li>
  );
}

/** Every project's checks, or one project's, newest first, with the scope switch on top. */
export function Sidebar({
  projects,
  scope,
  onScope,
  selected,
  onSelect,
  error,
}: {
  projects: ProjectGroup[];
  /** The checks directory of the one project shown, or null for all. */
  scope: string | null;
  onScope: (scope: string | null) => void;
  selected: CheckReference | null;
  onSelect: (ref: CheckReference) => void;
  /** Why the list could not be read again, when the last read failed. */
  error: unknown;
}) {
  const scoped = scope
    ? projects.find((project) => project.checks_directory === scope)
    : undefined;
  const count = projects.reduce(
    (sum, project) => sum + project.checks.length,
    0,
  );
  const selectedIn = (project: ProjectGroup) =>
    selected?.checks_directory === project.checks_directory
      ? selected.check_id
      : null;
  return (
    <nav aria-label="Checks" className="flex h-full min-h-0 flex-col bg-panel">
      <div className="flex shrink-0 flex-col gap-2 border-b border-line p-2">
        <Menu>
          <MenuTrigger
            render={
              <button
                type="button"
                aria-label="Projects shown"
                className="flex h-8 w-full min-w-0 items-center gap-2 rounded-md border border-line-control bg-field px-2 text-left hover:bg-hover aria-expanded:bg-panel"
              />
            }
          >
            <Icon
              name={scoped ? "folder" : "layers"}
              className="shrink-0 text-ink-muted"
            />
            <span className="min-w-0 flex-1 truncate font-medium">
              {scoped ? scoped.name : "All projects"}
            </span>
            <Icon name="chevron" className="shrink-0 text-ink-muted" />
          </MenuTrigger>
          <MenuContent className="max-h-[min(480px,calc(100dvh-96px))] w-80 max-w-[calc(100vw-16px)] overflow-y-auto">
            <MenuRadioGroup
              className="overflow-hidden"
              value={scope ?? "all"}
              onValueChange={(value) =>
                onScope(value === "all" ? null : String(value))
              }
            >
              <MenuRadioItem value="all" closeOnClick>
                All projects
              </MenuRadioItem>
              <MenuSeparator />
              <MenuGroupLabel>Projects</MenuGroupLabel>
              {projects.map((project) => (
                <MenuRadioItem
                  key={project.checks_directory}
                  value={project.checks_directory}
                  closeOnClick
                  className="h-auto py-1.5"
                  title={project.root}
                >
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate">{project.name}</span>
                    <span className="truncate mono-annotation text-ink-muted">
                      {shortPath(project.root)}
                    </span>
                  </span>
                </MenuRadioItem>
              ))}
            </MenuRadioGroup>
          </MenuContent>
        </Menu>
        {scoped && (
          <div className="flex min-w-0 items-center gap-2 px-1">
            <span
              title={scoped.root}
              className="min-w-0 flex-1 truncate mono-annotation text-ink-muted"
            >
              {shortPath(scoped.root)}
            </span>
            <button
              type="button"
              onClick={() => onScope(null)}
              className="shrink-0 rounded-sm px-1 text-caption text-accent-ink hover:bg-hover"
            >
              Show all
            </button>
          </div>
        )}
      </div>
      {error !== null && (
        <ErrorNotice
          error={error}
          title="The list may be out of date."
          className="m-2 text-caption"
        />
      )}
      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {count === 0 ? (
          <p className="p-3 text-caption text-ink-muted">
            Checks show here as your agent starts them.
          </p>
        ) : scoped ? (
          <ol className="flex flex-col gap-px">
            {scoped.checks.map((summary) => (
              <CheckRow
                key={summary.check_id}
                summary={summary}
                indent={false}
                selected={summary.check_id === selectedIn(scoped)}
                onSelect={() => onSelect(refOf(summary))}
              />
            ))}
          </ol>
        ) : (
          <ol className="flex flex-col gap-0.5">
            {projects.map((project) => (
              <ProjectTree
                key={project.checks_directory}
                project={project}
                selected={selectedIn(project)}
                onSelect={onSelect}
              />
            ))}
          </ol>
        )}
      </div>
    </nav>
  );
}
