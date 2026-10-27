import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EvidenceThumb } from "@/components/EvidenceThumb";
import { EvidenceImage } from "@/components/EvidenceImage";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Markdown } from "@/components/ui/markdown";
import { Segmented } from "@/components/ui/segmented";
import { Elapsed, StatusMark } from "@/components/ui/status-mark";
import { latestSaid } from "@/lib/activity";
import { isImage, resolver } from "@/lib/evidence";
import { plural } from "@/lib/format";
import { indexReport, revealReportHeading } from "@/lib/report";
import { isRunning, type Check } from "@/lib/store";
import { dateTime, offset } from "@/lib/time";
import { useUi } from "@/lib/ui";
import { cn } from "@/lib/utils";

/** How the check ran, above whatever its agent wrote: when, against what, with which model. */
function CheckLine({ check }: { check: Check }) {
  const timed = {
    state: check.state,
    started_at: check.summary.started_at,
    ended_at: check.record?.ended_at ?? check.summary.ended_at,
  };
  return (
    <p className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-ink-muted">
      <StatusMark check={timed} className="text-ink" />
      <span className="mono-annotation">
        {dateTime(check.summary.started_at)}
      </span>
      {check.summary.target && (
        <span
          className="min-w-0 truncate mono-annotation"
          title={check.summary.target}
        >
          {check.summary.target}
        </span>
      )}
      <span className="mono-annotation">{check.summary.model}</span>
    </p>
  );
}

/** The raw Markdown, exactly what the calling agent reads, with line numbers. */
export function Source({ markdown }: { markdown: string }) {
  const lines = markdown.replace(/\n$/, "").split("\n");
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-panel">
      <div className="flex min-w-max py-3 font-mono text-label/5">
        <div
          aria-hidden
          className="sticky left-0 shrink-0 bg-panel pr-3 pl-4 text-right text-ink-faint select-none"
        >
          {lines.map((_, index) => (
            <div key={index}>{index + 1}</div>
          ))}
        </div>
        <pre className="pr-6 whitespace-pre text-ink">{markdown}</pre>
      </div>
    </div>
  );
}

/** A running check: what its agent said last, and the screenshots it has saved so far. */
function Live({ check }: { check: Check }) {
  const { openEvidence, navigate } = useUi();
  const said = latestSaid(check.activity?.entries ?? []);
  const images = check.evidence.filter(isImage);
  const newest = [...images]
    .sort((a, b) => Date.parse(b.modified_at) - Date.parse(a.modified_at))
    .slice(0, 6);
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <h1 className="flex items-center gap-2.5 text-[24px]/8 font-semibold tracking-[-0.015em]">
          <LoadingMark size={12} />
          Checking
          <Elapsed
            check={{
              state: check.state,
              started_at: check.summary.started_at,
              ended_at: null,
            }}
            className="text-[13px] text-ink-muted"
          />
        </h1>
        {said ? (
          <div className="flex max-w-[72ch] gap-3">
            <span className="mt-1 shrink-0 mono-annotation text-ink-faint">
              {offset(check.summary.started_at, said.time)}
            </span>
            <Markdown className="text-[14px]/[22px]">{said.text}</Markdown>
          </div>
        ) : (
          <p className="text-ink-muted">
            Reading the request and reaching the software.
          </p>
        )}
        <p className="text-caption text-ink-muted">
          The report shows here when the agent writes it.
        </p>
      </div>
      <section className="flex flex-col gap-2.5">
        <h2 className="flex items-baseline gap-2 text-label">
          Newest screenshots
          <span className="mono-annotation text-ink-muted">
            {images.length}
          </span>
          {check.evidence.length > 0 && (
            <button
              type="button"
              onClick={() => navigate({ kind: "evidence" })}
              className="ml-auto rounded-sm px-1 font-normal text-accent-ink hover:bg-hover"
            >
              {plural(check.evidence.length, "file")} saved so far
            </button>
          )}
        </h2>
        {newest.length > 0 ? (
          <div className="grid animate-[appear_300ms_ease-out] grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
            {newest.map((item) => (
              <EvidenceThumb
                key={item.path}
                checkRef={check.ref}
                item={item}
                className="w-full"
                onOpen={() =>
                  openEvidence(
                    item.path,
                    newest.map((each) => each.path),
                  )
                }
              />
            ))}
          </div>
        ) : (
          <p className="text-ink-muted">
            Screenshots show here as they are taken.
          </p>
        )}
      </section>
    </div>
  );
}

/** The agent's report, with evidence links, paths, and bare file names opening in the viewer. */
export function ReportMarkdown({
  check,
  children,
}: {
  check: Check;
  children: string;
}) {
  const { openEvidence } = useUi();
  const resolve = useMemo(() => resolver(check.evidence), [check.evidence]);
  const names = useMemo(
    () => check.evidence.map((item) => item.name),
    [check.evidence],
  );
  // Stable, so the Markdown is not rendered again for a new opener.
  const opener = useRef(openEvidence);
  useEffect(() => {
    opener.current = openEvidence;
  });
  const onEvidence = useCallback((path: string) => opener.current(path), []);
  const renderImage = useCallback(
    (source: string, caption: string) => {
      const path = resolve(source);
      const item = check.evidence.find((item) => item.path === path);
      if (!item || !isImage(item)) {
        return null;
      }
      return (
        <span className="my-3 block">
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onEvidence(item.path);
            }}
            title={`Open ${item.name}`}
            className="flex max-w-full flex-col gap-2 text-left"
          >
            <EvidenceImage
              checkRef={check.ref}
              item={item}
              alt={caption}
              className="block min-h-24 max-w-full rounded-md border border-line bg-field hover:border-line-control"
            />
            <span className="text-label text-ink-muted">
              {caption || item.name}
            </span>
          </button>
        </span>
      );
    },
    [check.evidence, check.ref, resolve, onEvidence],
  );
  return (
    <Markdown
      report
      className="text-[14px]/[22px]"
      onEvidence={onEvidence}
      resolve={resolve}
      evidenceNames={names}
      renderImage={renderImage}
    >
      {children}
    </Markdown>
  );
}

/** The report page: how the check ran, then the agent's Markdown, with an outline from its ## headings. */
export function ReportPage({ check }: { check: Check }) {
  const { navigate, showInActivity } = useUi();
  const [view, setView] = useState<"report" | "source">("report");
  const article = useRef<HTMLElement>(null);
  const index = indexReport(check.report);
  const outline = view === "report" && index.headings.length >= 2;
  const running = isRunning(check.state);
  return (
    <div className="@container flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line pb-3">
        <CheckLine check={check} />
        <span className="flex-1" />
        <span className="flex flex-wrap items-center gap-1.5">
          <Button size="sm" onClick={() => navigate({ kind: "evidence" })}>
            <Icon name="image" />
            Evidence
            {check.detail && (
              <span className="mono-annotation text-ink-muted">
                {check.evidence.length}
              </span>
            )}
          </Button>
          <Button size="sm" onClick={() => navigate({ kind: "details" })}>
            <Icon name="list" />
            Details
          </Button>
          {check.report && (
            <Segmented
              label="Show"
              size="sm"
              value={view}
              onChange={setView}
              options={[
                { value: "report", label: "Report" },
                { value: "source", label: "Source" },
              ]}
            />
          )}
        </span>
      </div>
      {check.detail === null ? (
        <p className="flex items-center gap-2 py-10 text-ink-muted">
          <LoadingMark />
          Reading the check
        </p>
      ) : check.report === null && running ? (
        <Live check={check} />
      ) : check.report === null ? (
        <EmptyState
          tile={<Icon name="file" size={24} />}
          tileClassName="bg-pastel-stone"
          title="No report"
          className="rounded-lg"
          action={
            <span className="mt-2 flex flex-wrap justify-center gap-2">
              <Button variant="secondary" onClick={() => showInActivity({})}>
                <Icon name="list" />
                See what it did
              </Button>
              {check.evidence.length > 0 && (
                <Button
                  variant="secondary"
                  onClick={() => navigate({ kind: "evidence" })}
                >
                  <Icon name="image" />
                  {plural(check.evidence.length, "evidence file")}
                </Button>
              )}
            </span>
          }
        >
          {check.state === "cancelled"
            ? "It was cancelled before its agent wrote a report."
            : check.state === "timed-out"
              ? "It ran out of time before its agent wrote a report."
              : check.state === "crashed"
                ? "Its process stopped before its agent wrote a report."
                : "Its agent did not write a report."}
        </EmptyState>
      ) : view === "source" ? (
        <Source markdown={check.report} />
      ) : (
        <div
          className={cn(
            "grid gap-x-10 gap-y-5",
            outline && "@[880px]:grid-cols-[minmax(0,1fr)_180px]",
          )}
        >
          <article ref={article} className="max-w-[880px] min-w-0">
            <ReportMarkdown check={check}>{check.report}</ReportMarkdown>
          </article>
          {outline && (
            // Beside the report when there is room, a line of links above it when there is less, hidden when narrow.
            <nav
              aria-label="On this page"
              className="hidden @max-[880px]:order-first @[600px]:block"
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 @[880px]:sticky @[880px]:top-6 @[880px]:flex-col @[880px]:gap-1 @[880px]:border-l @[880px]:border-line @[880px]:pl-4">
                <span className="text-caption text-ink-muted @[880px]:mb-1">
                  On this page
                </span>
                {index.headings.map((heading) => (
                  <a
                    key={heading.id}
                    href={`#${heading.id}`}
                    onClick={(event) => {
                      event.preventDefault();
                      if (article.current) {
                        revealReportHeading(article.current, heading.id);
                      }
                    }}
                    className="text-label font-normal text-ink-muted hover:text-ink"
                  >
                    {heading.text}
                  </a>
                ))}
              </div>
            </nav>
          )}
        </div>
      )}
    </div>
  );
}
