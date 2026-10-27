import { useEffect, useRef, useState } from "react";

import { CheckMenu } from "@/components/canvas/CheckMenu";
import { DetailsPage } from "@/components/canvas/DetailsPage";
import { EvidencePage } from "@/components/canvas/EvidencePage";
import { EvidenceViewer } from "@/components/canvas/EvidenceViewer";
import { ReportPage } from "@/components/canvas/ReportPage";
import { ErrorNotice } from "@/components/ErrorNotice";
import { Welcome } from "@/components/Welcome";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Tooltip } from "@/components/ui/tooltip";
import { DEFAULT_FILTER, type EvidenceFilter } from "@/lib/evidence";
import { middle } from "@/lib/format";
import { pageOf, trail, type Route } from "@/lib/nav";
import type { Check } from "@/lib/store";
import { useUi } from "@/lib/ui";
import { cn } from "@/lib/utils";

function label(route: Route): string {
  switch (route.kind) {
    case "report":
      return "Report";
    case "evidence":
      return "Evidence";
    case "details":
      return "Details";
    case "file":
      return middle(route.path.replace(/^evidence\//, ""), 30);
  }
}

/** Back, forward, and the trail from the report to where the canvas is; each crumb goes there. */
function Crumbs({ check }: { check: Check }) {
  const { nav, navigate, goBack, goForward } = useUi();
  const crumbs = trail(nav.current);
  return (
    <div className="flex h-10 shrink-0 items-center gap-1 border-b border-line bg-panel px-1.5">
      <Tooltip content="Back" keys="Esc">
        <Button
          size="sm"
          icon
          aria-label="Back"
          disabled={nav.back.length === 0 && crumbs.length < 2}
          onClick={goBack}
        >
          <Icon name="arrow-left" />
        </Button>
      </Tooltip>
      <Tooltip content="Forward">
        <Button
          size="sm"
          icon
          aria-label="Forward"
          disabled={nav.forward.length === 0}
          onClick={goForward}
        >
          <Icon name="arrow-right" />
        </Button>
      </Tooltip>
      <span aria-hidden className="mx-1 h-4 w-px bg-line" />
      <nav
        aria-label="Breadcrumb"
        className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden text-label"
      >
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          const between = index > 0 && !last;
          return (
            <span
              key={index}
              className={cn(
                "flex items-center gap-1",
                last
                  ? "min-w-0 flex-1"
                  : between
                    ? "max-w-[40%] min-w-0 max-sm:hidden"
                    : "shrink-0",
              )}
            >
              {index > 0 && (
                <Icon
                  name="chevron"
                  className="size-3.5 shrink-0 -rotate-90 text-ink-faint"
                />
              )}
              {last ? (
                <span
                  aria-current="page"
                  className={cn(
                    "min-w-0 truncate px-1",
                    crumb.kind === "file" && "mono-value",
                  )}
                >
                  {label(crumb)}
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => navigate(crumb)}
                  title={label(crumb)}
                  className="min-w-0 truncate rounded-sm px-1 text-ink-muted hover:bg-hover hover:text-ink"
                >
                  {label(crumb)}
                </button>
              )}
            </span>
          );
        })}
      </nav>
      <CheckMenu check={check} />
    </div>
  );
}

/** The canvas: one place that starts at the report and drills down, with files opened over it. */
export function ReportCanvas({
  check,
  empty,
  flash,
}: {
  check: Check | null;
  /** Whether there are no checks at all, so the canvas says when to run one. */
  empty: boolean;
  flash: number;
}) {
  const { nav, replaceRoute, goBack, showInActivity, toast } = useUi();
  const [filter, setFilter] = useState<EvidenceFilter>(DEFAULT_FILTER);
  const [flashing, setFlashing] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const pageKey = JSON.stringify(pageOf(nav.current));

  useEffect(() => {
    if (flash === 0) {
      return;
    }
    const start = setTimeout(() => setFlashing(true), 0);
    const end = setTimeout(() => setFlashing(false), 1400);
    return () => {
      clearTimeout(start);
      clearTimeout(end);
    };
  }, [flash]);

  // A new page starts at its top; closing a file returns to the page as it was.
  useEffect(() => {
    scroller.current?.scrollTo({ top: 0 });
  }, [pageKey, check?.key]);

  if (!check) {
    return (
      <div className="h-full overflow-y-auto bg-canvas">
        {empty ? (
          <Welcome />
        ) : (
          <p className="p-6 text-center text-ink-muted">
            Pick a check to see its report.
          </p>
        )}
      </div>
    );
  }
  const page = pageOf(nav.current);
  const file = nav.current.kind === "file" ? nav.current : null;
  return (
    <section
      aria-label="Report"
      className={cn(
        "relative flex h-full min-h-0 flex-col bg-canvas",
        flashing && "animate-[flash_1.4s_ease-out]",
      )}
    >
      <Crumbs check={check} />
      <div className="relative min-h-0 flex-1">
        <div ref={scroller} className="absolute inset-0 overflow-y-auto">
          {check.error !== null && check.detail === null ? (
            <div className="mx-auto max-w-[720px] px-8 pt-7 max-sm:px-4">
              <ErrorNotice
                error={check.error}
                title="Could not read this check."
              />
            </div>
          ) : page.kind === "evidence" ? (
            <EvidencePage check={check} filter={filter} onFilter={setFilter} />
          ) : (
            <div className="mx-auto w-full max-w-[1280px] px-8 pt-7 pb-20 max-sm:px-4">
              {check.error !== null && (
                <ErrorNotice
                  error={check.error}
                  title="Could not read this check again."
                  className="mb-5"
                />
              )}
              {page.kind === "report" && <ReportPage check={check} />}
              {page.kind === "details" && <DetailsPage check={check} />}
            </div>
          )}
        </div>
        {file && (
          <EvidenceViewer
            key={check.key}
            check={check}
            state={{ path: file.path, list: file.list }}
            onChange={(state) =>
              replaceRoute({
                kind: "file",
                path: state.path,
                list: state.list,
                from: file.from,
              })
            }
            onClose={goBack}
            onShowInActivity={(path) => showInActivity({ path })}
            toast={toast}
          />
        )}
      </div>
    </section>
  );
}
