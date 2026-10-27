import { EvidenceThumb } from "@/components/EvidenceThumb";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Segmented } from "@/components/ui/segmented";
import {
  DEFAULT_FILTER,
  isImage,
  KIND_ICONS,
  KIND_LABELS,
  KINDS,
  reportOrder,
  type Evidence,
  type EvidenceFilter,
  type EvidenceKind,
} from "@/lib/evidence";
import { bytes } from "@/lib/format";
import { isRunning, type Check } from "@/lib/store";
import { offset } from "@/lib/time";
import { useUi } from "@/lib/ui";

function FileRow({
  item,
  started,
  onOpen,
}: {
  item: Evidence;
  started: string;
  onOpen: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="flex h-8 w-full min-w-0 items-center gap-2.5 px-3 text-left -outline-offset-2 hover:bg-hover"
      >
        <Icon
          name={KIND_ICONS[item.kind]}
          className="shrink-0 text-ink-muted"
        />
        <span className="min-w-0 flex-1 truncate mono-value">{item.name}</span>
        <span className="w-16 shrink-0 text-right mono-annotation text-ink-muted">
          {bytes(item.size)}
        </span>
        <span className="w-12 shrink-0 text-right mono-annotation text-ink-faint max-sm:hidden">
          {offset(started, item.modified_at)}
        </span>
      </button>
    </li>
  );
}

function Group({
  check,
  title,
  note,
  items,
  onOpen,
}: {
  check: Check;
  title: string;
  note?: string;
  items: Evidence[];
  onOpen: (item: Evidence) => void;
}) {
  const images = items.filter(isImage);
  const files = items.filter((item) => !isImage(item));
  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-col gap-0.5 px-0.5">
        <span className="flex items-center gap-2 text-label">
          <h3>{title}</h3>
          <span className="mono-annotation text-ink-muted">{items.length}</span>
          <span aria-hidden className="ml-2 h-px flex-1 bg-line" />
        </span>
        {note && <p className="text-caption text-ink-muted">{note}</p>}
      </header>
      {images.length > 0 && (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-3 gap-y-3.5">
          {images.map((item) => (
            <EvidenceThumb
              key={item.path}
              checkRef={check.ref}
              item={item}
              onOpen={() => onOpen(item)}
              className="w-full"
            />
          ))}
        </div>
      )}
      {files.length > 0 && (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-panel">
          {files.map((item) => (
            <FileRow
              key={item.path}
              item={item}
              started={check.summary.started_at}
              onOpen={() => onOpen(item)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

/** Everything the check saved: what the report cites, then what it does not, filtered by kind and name. */
export function EvidencePage({
  check,
  filter,
  onFilter,
}: {
  check: Check;
  filter: EvidenceFilter;
  onFilter: (filter: EvidenceFilter) => void;
}) {
  const { openEvidence } = useUi();
  const query = filter.query.trim().toLowerCase();
  const all = reportOrder(check.report, check.evidence);
  const shown = all.filter(
    (item) =>
      (filter.kind === "all" || item.kind === filter.kind) &&
      (!query || item.name.toLowerCase().includes(query)),
  );
  const hasReport = check.report !== null;
  const cited = hasReport ? shown.filter((item) => item.referenced) : [];
  const uncited = hasReport ? shown.filter((item) => !item.referenced) : shown;
  // The viewer steps through files in the order they show: by group, pictures before files.
  const visual = (items: Evidence[]) => [
    ...items.filter(isImage),
    ...items.filter((item) => !isImage(item)),
  ];
  const list = [...visual(cited), ...visual(uncited)].map((item) => item.path);
  const open = (item: Evidence) => openEvidence(item.path, list);
  const count = (kind: EvidenceKind) =>
    all.filter((item) => item.kind === kind).length;
  const kinds = KINDS.filter((kind) => count(kind) > 0);
  const running = isRunning(check.state);

  return (
    <div className="flex min-h-full flex-col">
      <div className="sticky top-0 z-10 flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-panel px-4 py-2">
        <Segmented
          label="Kind"
          size="sm"
          className="max-w-full overflow-x-auto"
          value={filter.kind}
          onChange={(kind) => onFilter({ ...filter, kind })}
          options={[
            { value: "all", label: check.detail ? `All ${all.length}` : "All" },
            ...kinds.map((kind) => ({
              value: kind,
              label: `${KIND_LABELS[kind]} ${count(kind)}`,
            })),
          ]}
        />
        <span className="flex-1" />
        <label className="flex h-6 w-48 min-w-0 items-center gap-1.5 rounded-sm border border-line-control bg-field pr-1 pl-2 text-ink-muted focus-within:border-ink focus-within:bg-panel">
          <Icon name="search" />
          <input
            type="search"
            value={filter.query}
            onChange={(event) =>
              onFilter({ ...filter, query: event.target.value })
            }
            placeholder="Filter by name"
            aria-label="Filter evidence by name"
            className="min-w-0 flex-1 bg-transparent text-label font-normal text-ink outline-none placeholder:text-ink-muted [&::-webkit-search-cancel-button]:hidden"
          />
        </label>
        {check.detail && (
          <span className="mono-annotation text-ink-muted">
            {shown.length} of {all.length}
          </span>
        )}
      </div>
      <div className="flex-1">
        {check.detail === null ? (
          <p className="flex items-center gap-2 px-6 py-10 text-ink-muted">
            <LoadingMark />
            Reading the evidence
          </p>
        ) : shown.length === 0 ? (
          <div className="grid place-items-center p-10">
            <EmptyState
              tile={<Icon name="image" size={24} />}
              tileClassName="bg-pastel-lilac"
              title={
                all.length === 0
                  ? running
                    ? "No evidence saved yet"
                    : "This check saved no evidence"
                  : "Nothing matches these filters"
              }
              action={
                all.length > 0 && (
                  <Button
                    variant="secondary"
                    onClick={() => onFilter(DEFAULT_FILTER)}
                    className="mt-2"
                  >
                    Show all evidence
                  </Button>
                )
              }
              className="w-full max-w-110 rounded-lg"
            >
              {all.length === 0
                ? running
                  ? "Screenshots, network captures, and scripts show here as the check saves them."
                  : "Its activity shows what it did."
                : "Try another kind, or clear the name filter."}
            </EmptyState>
          </div>
        ) : (
          <div className="flex w-full flex-col gap-8 px-6 pt-5 pb-16 max-sm:px-4">
            {cited.length > 0 && (
              <Group
                check={check}
                title="Cited in the report"
                items={visual(cited)}
                onOpen={open}
              />
            )}
            {uncited.length > 0 && (
              <Group
                check={check}
                title={
                  hasReport
                    ? "Not cited in the report"
                    : running
                      ? "Saved so far"
                      : "Evidence"
                }
                note={
                  hasReport
                    ? "Saved by the check, but the report does not name them."
                    : undefined
                }
                items={visual(uncited)}
                onOpen={open}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
