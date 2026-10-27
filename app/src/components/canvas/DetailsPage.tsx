import { useState, type ReactNode } from "react";

import { PathText } from "@/components/PathText";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { StatusMark } from "@/components/ui/status-mark";
import type { CheckReference, CheckSummary } from "@/lib/api";
import { compact, providerName, shortPath, whole } from "@/lib/format";
import {
  elapsedSeconds,
  isRunning,
  labelOf,
  useStore,
  type Check,
} from "@/lib/store";
import { dateTime, duration, useNow } from "@/lib/time";
import { useUi } from "@/lib/ui";
import { copyText } from "@/lib/utils";

function Copy({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="sm"
      icon
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
      onClick={() =>
        void copyText(text).then((done) => {
          setCopied(done);
          setTimeout(() => setCopied(false), 1500);
        })
      }
    >
      <Icon name={copied ? "check" : "copy"} />
    </Button>
  );
}

function Pair({
  label,
  children,
  mono = true,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="grid grid-cols-[136px_minmax(0,1fr)] items-baseline gap-3 max-sm:grid-cols-1 max-sm:gap-0.5">
      <dt className="text-label font-normal text-ink-muted">{label}</dt>
      <dd className={mono ? "mono-value wrap-break-word" : "wrap-break-word"}>
        {children}
      </dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5 rounded-lg border border-line bg-panel p-4">
      <h2 className="text-label text-ink-muted">{title}</h2>
      {children}
    </section>
  );
}

/** A link to another check, which shows it when it is in the list. */
function CheckLink({
  reference,
  checks,
}: {
  reference: CheckReference;
  checks: CheckSummary[];
}) {
  const { selectCheck } = useUi();
  const listed = checks.find(
    (each) =>
      each.check_id === reference.check_id &&
      each.project.checks_directory === reference.checks_directory,
  );
  if (!listed) {
    return (
      <span className="flex flex-col">
        <span className="mono-value">{reference.check_id}</span>
        <span className="text-caption text-ink-muted">
          Not in any project Reality Check knows on this machine.
        </span>
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => selectCheck(reference)}
      className="flex w-full min-w-0 flex-col rounded-md border border-line px-2.5 py-1.5 text-left hover:border-line-control hover:bg-hover"
    >
      <span className="line-clamp-2">{labelOf(listed.request)}</span>
      <span className="flex items-center gap-2 mono-annotation text-ink-muted">
        {listed.check_id}
        <span>{dateTime(listed.started_at)}</span>
      </span>
    </button>
  );
}

/** Everything about how a check was set up, how it ran, and what it used. How it ran is not what it found. */
export function DetailsPage({ check }: { check: Check }) {
  const { checks } = useStore();
  const now = useNow(isRunning(check.state));
  const record = check.record;
  const summary = check.summary;
  const usage = record?.usage;
  const billing = Object.entries(usage?.billing ?? {});
  const resumes = check.detail?.resumes ?? null;
  const previous = check.detail?.previous_checks ?? [];
  const timed = {
    state: check.state,
    started_at: summary.started_at,
    ended_at: record?.ended_at ?? summary.ended_at,
  };
  return (
    <div className="flex max-w-[880px] flex-col gap-4">
      <Section title="Request">
        <div className="flex items-start gap-2">
          <p className="min-w-0 flex-1 wrap-break-word whitespace-pre-wrap">
            {summary.request}
          </p>
          <Copy text={summary.request} label="Copy the request" />
        </div>
        <dl className="flex flex-col gap-1.5 border-t border-line pt-2.5">
          <Pair label="Target">
            {summary.target ?? (
              <span className="text-ink-muted">Taken from the request</span>
            )}
          </Pair>
          <Pair label="Started by" mono={false}>
            {summary.origin === "unknown" ? (
              <span className="text-ink-muted">Not recorded</span>
            ) : (
              <span className="mono-value">{summary.origin}</span>
            )}
          </Pair>
        </dl>
      </Section>
      <Section title="How it ran">
        <dl className="flex flex-col gap-1.5">
          <Pair label="Execution" mono={false}>
            <StatusMark check={timed} />
          </Pair>
          <Pair label="Started">{dateTime(summary.started_at)}</Pair>
          <Pair label="Ended">
            {timed.ended_at && !isRunning(check.state) ? (
              dateTime(timed.ended_at)
            ) : (
              <span className="text-ink-muted">Still running</span>
            )}
          </Pair>
          <Pair label="Elapsed">{duration(elapsedSeconds(timed, now))}</Pair>
          <Pair label="Timeout">
            {record?.timeout_seconds
              ? duration(record.timeout_seconds)
              : record
                ? "None"
                : ""}
          </Pair>
        </dl>
      </Section>
      <Section title="Agent">
        <dl className="flex flex-col gap-1.5">
          <Pair label="Agent provider" mono={false}>
            {providerName(summary.agent_provider)}
          </Pair>
          <Pair label="Model">{summary.model}</Pair>
          <Pair label="Reasoning effort">
            {record?.reasoning_effort ?? (
              <span className="text-ink-muted">None sent</span>
            )}
          </Pair>
          {record?.session_id && (
            <Pair label="Agent session">{record.session_id}</Pair>
          )}
        </dl>
      </Section>
      <Section title="Usage">
        {!usage || usage.model_calls === 0 ? (
          <p className="text-ink-muted">
            {isRunning(check.state)
              ? "No model calls counted yet."
              : "No model calls were counted."}
          </p>
        ) : (
          <dl className="flex flex-col gap-1.5">
            <Pair label="Model calls">{whole(usage.model_calls)}</Pair>
            <Pair label="New input tokens">
              {compact(usage.fresh_input_tokens)}
            </Pair>
            <Pair label="Cache reads">{compact(usage.cache_read_tokens)}</Pair>
            <Pair label="Cache writes">
              {compact(usage.cache_write_tokens)}
            </Pair>
            <Pair label="Output tokens">{compact(usage.output_tokens)}</Pair>
            <Pair label="Reasoning tokens">
              {compact(usage.reasoning_tokens)}
            </Pair>
            {billing.map(([unit, amount]) => (
              <Pair key={unit} label={`Billed in ${unit}`}>
                {amount.toFixed(2)} {unit}
              </Pair>
            ))}
          </dl>
        )}
      </Section>
      {(resumes || previous.length > 0 || check.continuedBy.length > 0) && (
        <Section title="Related checks">
          <dl className="flex flex-col gap-2.5">
            {resumes && (
              <Pair label="Continues" mono={false}>
                <CheckLink reference={resumes} checks={checks} />
              </Pair>
            )}
            {previous.length > 0 && (
              <Pair label="Builds on" mono={false}>
                <span className="flex flex-col gap-1.5">
                  {previous.map((reference) => (
                    <CheckLink
                      key={`${reference.checks_directory}/${reference.check_id}`}
                      reference={reference}
                      checks={checks}
                    />
                  ))}
                </span>
              </Pair>
            )}
            {check.continuedBy.length > 0 && (
              <Pair label="Continued by" mono={false}>
                <span className="flex flex-col gap-1.5">
                  {check.continuedBy.map((each) => (
                    <CheckLink
                      key={each.check_id}
                      reference={{
                        check_id: each.check_id,
                        checks_directory: each.project.checks_directory,
                      }}
                      checks={checks}
                    />
                  ))}
                </span>
              </Pair>
            )}
          </dl>
        </Section>
      )}
      <Section title="Files">
        <dl className="flex flex-col gap-2">
          <Pair label="Check id">{check.id}</Pair>
          {check.directory && (
            <Pair label="Check folder">
              <span className="flex items-start gap-2">
                <span className="min-w-0 flex-1" title={check.directory}>
                  <PathText path={shortPath(check.directory)} />
                </span>
                <Copy text={check.directory} label="Copy the path" />
              </span>
            </Pair>
          )}
          {check.activity?.processLog && (
            <Pair label="Process log">
              <span className="flex items-start gap-2">
                <span
                  className="min-w-0 flex-1"
                  title={check.activity.processLog}
                >
                  <PathText path={shortPath(check.activity.processLog)} />
                </span>
                <Copy text={check.activity.processLog} label="Copy the path" />
              </span>
            </Pair>
          )}
        </dl>
      </Section>
    </div>
  );
}
