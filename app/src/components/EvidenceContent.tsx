import { useState, type ReactNode } from "react";

import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Markdown } from "@/components/ui/markdown";
import { Notice } from "@/components/ui/notice";
import type { CheckReference } from "@/lib/api";
import { describe } from "@/lib/errors";
import type { Evidence } from "@/lib/evidence";
import { useEvidenceText, useEvidenceUrl } from "@/lib/files";
import { bytes } from "@/lib/format";
import { cn } from "@/lib/utils";

function Reading() {
  return (
    <div className="flex items-center gap-2 p-4 text-ink-muted">
      <LoadingMark />
      Reading the file
    </div>
  );
}

// ---------- JSON tree ----------

function Scalar({ value }: { value: unknown }) {
  if (typeof value === "string") {
    const long = value.length > 240;
    return <LongString value={value} long={long} />;
  }
  return (
    <span
      className={cn(
        value === null
          ? "text-ink-faint"
          : typeof value === "number"
            ? "text-accent-ink"
            : "text-ink",
      )}
    >
      {String(value)}
    </span>
  );
}

function LongString({ value, long }: { value: string; long: boolean }) {
  const [open, setOpen] = useState(false);
  const shown = long && !open ? `${value.slice(0, 240)}...` : value;
  return (
    <span className="whitespace-pre-wrap text-ink-muted">
      "{shown}"
      {long && (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="ml-1 rounded-sm px-1 text-accent-ink hover:bg-hover"
        >
          {open ? "less" : `${value.length.toLocaleString()} chars`}
        </button>
      )}
    </span>
  );
}

function Node({
  name,
  value,
  depth,
  last,
}: {
  name: ReactNode;
  value: unknown;
  depth: number;
  last: boolean;
}) {
  const composite = value !== null && typeof value === "object";
  const [open, setOpen] = useState(depth < 2);
  const [all, setAll] = useState(false);
  const comma = last ? "" : ",";
  if (!composite) {
    return (
      <div className="pl-4">
        {name}
        <Scalar value={value} />
        {comma}
      </div>
    );
  }
  const array = Array.isArray(value);
  const entries: [string, unknown][] = array
    ? (value as unknown[]).map((item, index) => [String(index), item])
    : Object.entries(value as Record<string, unknown>);
  const limit = all ? entries.length : 100;
  const [left, right] = array ? ["[", "]"] : ["{", "}"];
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center rounded-sm text-left hover:bg-hover"
      >
        <Icon
          name="chevron"
          className={cn(
            "size-4 text-ink-faint transition-transform",
            !open && "-rotate-90",
          )}
        />
        {name}
        <span className="text-ink-muted">{left}</span>
        {!open && (
          <span className="text-ink-faint">
            {" "}
            {entries.length}{" "}
            {array
              ? entries.length === 1
                ? "item"
                : "items"
              : entries.length === 1
                ? "key"
                : "keys"}{" "}
          </span>
        )}
        {!open && (
          <span className="text-ink-muted">
            {right}
            {comma}
          </span>
        )}
      </button>
      {open && (
        <>
          <div className="ml-2 border-l border-line pl-2">
            {entries.slice(0, limit).map(([key, item], index) => (
              <Node
                key={key}
                name={
                  array ? (
                    <span className="mr-1.5 text-ink-faint">{key}</span>
                  ) : (
                    <span className="mr-1.5 text-ink">"{key}":</span>
                  )
                }
                value={item}
                depth={depth + 1}
                last={index === Math.min(limit, entries.length) - 1}
              />
            ))}
            {entries.length > limit && (
              <button
                type="button"
                onClick={() => setAll(true)}
                className="ml-4 rounded-sm px-1 text-accent-ink hover:bg-hover"
              >
                Show {entries.length - limit} more
              </button>
            )}
          </div>
          <div className="pl-4 text-ink-muted">
            {right}
            {comma}
          </div>
        </>
      )}
    </div>
  );
}

function JsonTree({ value }: { value: unknown }) {
  return (
    <div className="mono-value leading-5 font-normal">
      <Node name={null} value={value} depth={0} last />
    </div>
  );
}

function parsed(text: string): { value: unknown } | null {
  try {
    return { value: JSON.parse(text) as unknown };
  } catch {
    return null;
  }
}

function JsonContent({ text }: { text: string }) {
  const json = parsed(text);
  if (!json) {
    return <TextContent text={text} />;
  }
  return (
    <div className="p-4">
      <JsonTree value={json.value} />
    </div>
  );
}

function JsonlContent({ text }: { text: string }) {
  const lines = text.split("\n").filter((line) => line.trim());
  return (
    <ol className="flex flex-col divide-y divide-line">
      {lines.map((line, index) => {
        let value: unknown = line;
        try {
          value = JSON.parse(line);
        } catch {
          // Shown as text.
        }
        return (
          <li key={index} className="flex gap-3 px-4 py-2">
            <span className="w-6 shrink-0 pt-0.5 text-right mono-annotation text-ink-faint">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <CollapsedTree value={value} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function CollapsedTree({ value }: { value: unknown }) {
  return (
    <div className="mono-value leading-5 font-normal">
      <Node name={null} value={value} depth={1} last />
    </div>
  );
}

// ---------- HAR ----------

type HarEntry = {
  startedDateTime: string;
  time: number;
  request: { method: string; url: string };
  response: {
    status: number;
    content?: { size?: number; mimeType?: string; text?: string };
  };
};

function parsedUrl(href: string): { host: string; rest: string } {
  try {
    const url = new URL(href);
    return { host: url.host, rest: `${url.pathname}${url.search}` };
  } catch {
    return { host: "", rest: href };
  }
}

/** A HAR size or time, which a recorder writes as -1 when it did not know it. */
function known(value: number | undefined): value is number {
  return typeof value === "number" && value >= 0;
}

function Unknown() {
  return (
    <span title="The recording does not say" className="text-ink-faint">
      unknown
    </span>
  );
}

function HarContent({ text }: { text: string }) {
  const [open, setOpen] = useState<number | null>(null);
  const har = parsed(text)?.value as
    { log?: { entries?: HarEntry[] } } | undefined;
  const entries = har?.log?.entries;
  if (!Array.isArray(entries)) {
    return <TextContent text={text} />;
  }
  const failed = entries.filter(
    (entry) => entry.response.status >= 400 || entry.response.status === 0,
  ).length;
  return (
    <div className="flex flex-col">
      <p className="flex items-center gap-2 border-b border-line px-4 py-2 text-label text-ink-muted">
        {entries.length} requests
        {failed > 0 ? (
          <span className="inline-flex items-center gap-1 text-danger">
            <Icon name="warning" />
            {failed} failed
          </span>
        ) : (
          <span>None failed</span>
        )}
      </p>
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-line-control text-left text-label text-ink-muted">
            <th className="w-16 py-1.5 pl-4 font-medium">Method</th>
            <th className="py-1.5 font-medium">URL</th>
            <th className="w-16 py-1.5 font-medium">Status</th>
            <th className="w-20 py-1.5 font-medium max-sm:hidden">Type</th>
            <th className="w-18 py-1.5 pr-4 text-right font-medium sm:pr-0">
              Size
            </th>
            <th className="w-18 py-1.5 pr-4 text-right font-medium max-sm:hidden">
              Time
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry, index) => {
            const bad =
              entry.response.status >= 400 || entry.response.status === 0;
            const url = parsedUrl(entry.request.url);
            const size = entry.response.content?.size;
            return [
              <tr
                key={index}
                onClick={() => setOpen(open === index ? null : index)}
                className={cn(
                  "cursor-default border-b border-line mono-value font-normal hover:bg-hover",
                  open === index && "bg-accent-soft",
                )}
              >
                <td className="py-1.5 pl-4">{entry.request.method}</td>
                <td
                  className="py-1.5 pr-3 break-all sm:max-w-0 sm:truncate"
                  title={entry.request.url}
                >
                  <span className="text-ink-faint">{url.host}</span>
                  {url.rest}
                </td>
                <td className={cn("py-1.5", bad && "text-danger")}>
                  <span className="inline-flex items-center gap-1">
                    {bad && <Icon name="warning" />}
                    {entry.response.status}
                  </span>
                </td>
                <td className="truncate py-1.5 text-ink-muted max-sm:hidden">
                  {(entry.response.content?.mimeType ?? "")
                    .split(";")[0]
                    .split("/")
                    .at(-1)}
                </td>
                <td className="py-1.5 pr-4 text-right whitespace-nowrap text-ink-muted sm:pr-0">
                  {known(size) ? bytes(size) : <Unknown />}
                </td>
                <td className="py-1.5 pr-4 text-right whitespace-nowrap text-ink-muted max-sm:hidden">
                  {known(entry.time) ? (
                    `${entry.time.toFixed(1)} ms`
                  ) : (
                    <Unknown />
                  )}
                </td>
              </tr>,
              open === index && (
                <tr key={`${index}-body`} className="border-b border-line">
                  <td colSpan={6} className="bg-field px-4 py-2">
                    <p className="mb-1.5 mono-value font-normal break-all text-ink">
                      {entry.request.method} {entry.request.url}
                    </p>
                    <pre className="overflow-x-auto font-mono text-label/4.5 whitespace-pre-wrap text-ink-muted">
                      {entry.response.content?.text
                        ? entry.response.content.text.slice(0, 6000)
                        : "No response body was recorded."}
                    </pre>
                  </td>
                </tr>
              ),
            ];
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------- text ----------

function TextContent({ text }: { text: string }) {
  const lines = text.replace(/\n$/, "").split("\n");
  const shown = lines.slice(0, 4000);
  return (
    <div className="flex min-w-max py-3 font-mono text-label/5">
      <div
        aria-hidden
        className="sticky left-0 shrink-0 bg-panel pr-3 pl-4 text-right text-ink-faint select-none"
      >
        {shown.map((_, index) => (
          <div key={index}>{index + 1}</div>
        ))}
      </div>
      <pre className="pr-6 whitespace-pre text-ink">{shown.join("\n")}</pre>
    </div>
  );
}

function Failed({ error }: { error: unknown }) {
  const { message, detail } = describe(error);
  return (
    <Notice className="m-4" title="Could not read this file.">
      {message}
      {detail && <Details text={detail} />}
    </Notice>
  );
}

/** The server's own words for a failure, out of the way until asked for. */
export function Details({ text }: { text: string }) {
  return (
    <details className="mt-1.5 text-caption text-ink-muted">
      <summary className="cursor-default select-none">Details</summary>
      <p className="mt-1 mono-annotation wrap-anywhere whitespace-pre-wrap">
        {text}
      </p>
    </details>
  );
}

function Video({
  checkRef,
  item,
}: {
  checkRef: CheckReference;
  item: Evidence;
}) {
  const { value: url, error } = useEvidenceUrl(checkRef, item);
  if (error) {
    return <Failed error={error} />;
  }
  if (!url) {
    return <Reading />;
  }
  return (
    <div className="grid size-full place-items-center bg-canvas p-4">
      <video src={url} controls className="max-h-full max-w-full bg-ink" />
    </div>
  );
}

/** A non-image evidence file, shown the way its kind reads best. HTML and SVG show as their text, never rendered. */
export function EvidenceContent({
  checkRef,
  item,
  onEvidence,
}: {
  checkRef: CheckReference;
  item: Evidence;
  onEvidence: (path: string) => void;
}) {
  if (item.kind === "video") {
    return <Video checkRef={checkRef} item={item} />;
  }
  return <Loaded checkRef={checkRef} item={item} onEvidence={onEvidence} />;
}

function Loaded({
  checkRef,
  item,
  onEvidence,
}: {
  checkRef: CheckReference;
  item: Evidence;
  onEvidence: (path: string) => void;
}) {
  const { value: text, error } = useEvidenceText(checkRef, item);
  if (error) {
    return <Failed error={error} />;
  }
  if (text === null) {
    return <Reading />;
  }
  switch (item.ext) {
    case "json":
      return <JsonContent text={text} />;
    case "jsonl":
    case "ndjson":
      return <JsonlContent text={text} />;
    case "har":
      return <HarContent text={text} />;
    case "md":
      return (
        <div className="px-6 py-4">
          <Markdown onEvidence={onEvidence}>
            {text.replace(
              /\]\((?!https?:|evidence\/)([^)]+)\)/g,
              "](evidence/$1)",
            )}
          </Markdown>
        </div>
      );
    default:
      return <TextContent text={text} />;
  }
}
