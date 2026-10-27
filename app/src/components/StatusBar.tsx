import { StatusMark } from "@/components/ui/status-mark";
import { plural, shortPath } from "@/lib/format";
import type { Check } from "@/lib/store";

/** The line along the bottom: how the check ran, which check it is, its model, its evidence, and its folder. */
export function StatusBar({ check }: { check: Check | null }) {
  return (
    <footer className="flex h-7 shrink-0 items-center gap-4 overflow-hidden border-t border-line bg-panel px-3 mono-annotation whitespace-nowrap text-ink-muted">
      {check ? (
        <>
          <StatusMark
            check={{
              state: check.state,
              started_at: check.summary.started_at,
              ended_at: check.record?.ended_at ?? check.summary.ended_at,
            }}
            className="text-caption"
          />
          <span className="text-ink">{check.id}</span>
          <span>{check.summary.model}</span>
          {check.detail && (
            <span>{plural(check.evidence.length, "evidence file")}</span>
          )}
          <span className="flex-1" />
          {check.directory && (
            <span className="truncate" title={check.directory}>
              {shortPath(check.directory)}
            </span>
          )}
        </>
      ) : (
        <span>No check selected</span>
      )}
    </footer>
  );
}
