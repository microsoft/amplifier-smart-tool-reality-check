import {
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { openLink } from "@/lib/host";
import {
  indexReport,
  reportSections,
  setReportSections,
  type MdNode,
} from "@/lib/report";
import { cn, copyText } from "@/lib/utils";

function CodeBlock({ children }: ComponentProps<"pre">) {
  const block = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  return (
    <div className="group/code relative mb-2 last:mb-0">
      <pre
        ref={block}
        className="overflow-x-auto rounded-md border border-line bg-field px-2.5 py-2 font-mono text-label/4.5 whitespace-pre [&>code]:border-0 [&>code]:bg-transparent [&>code]:p-0 [&>code]:font-normal"
      >
        {children}
      </pre>
      <Button
        variant="secondary"
        size="sm"
        icon
        aria-label={copied ? "Copied" : "Copy"}
        title={copied ? "Copied" : "Copy"}
        onClick={async () => {
          if (await copyText(block.current?.textContent ?? "")) {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }
        }}
        className="absolute top-1 right-1 opacity-0 group-hover/code:opacity-100 focus-visible:opacity-100"
      >
        <Icon name={copied ? "check" : "copy"} />
      </Button>
    </div>
  );
}

const LINK =
  "text-accent-ink underline decoration-accent-ink/40 underline-offset-2 hover:decoration-accent-ink";

/** An evidence link opens in the app's viewer; a web link opens in the browser through the host. */
function makeLink(
  onEvidence?: (path: string) => void,
  resolve?: (text: string) => string | null,
) {
  return function Link({ href, children }: ComponentProps<"a">) {
    const evidence =
      href && onEvidence
        ? (resolve?.(href) ??
          (href.startsWith("evidence/") ? decodeURIComponent(href) : null))
        : null;
    const web = href !== undefined && /^https?:\/\//i.test(href);
    return (
      <a
        href={href}
        title={evidence ? `Open ${evidence}` : href}
        onClick={(event) => {
          event.preventDefault();
          if (evidence && onEvidence) {
            onEvidence(evidence);
          } else if (web && href) {
            openLink(href);
          }
        }}
        className={LINK}
      >
        {children}
      </a>
    );
  };
}

const BASE: Components = {
  h1: ({ children }) => (
    <h3 className="mt-3 mb-1 text-[15px]/5.5 font-semibold first:mt-0">
      {children}
    </h3>
  ),
  h2: ({ children }) => (
    <h4 className="mt-3 mb-1 font-semibold first:mt-0">{children}</h4>
  ),
  h3: ({ children }) => (
    <h5 className="mt-2 mb-1 text-label font-semibold first:mt-0">
      {children}
    </h5>
  ),
  h4: ({ children }) => (
    <h6 className="mt-2 mb-1 text-label font-semibold first:mt-0">
      {children}
    </h6>
  ),
  h5: ({ children }) => (
    <h6 className="mt-2 mb-1 text-label font-semibold first:mt-0">
      {children}
    </h6>
  ),
  h6: ({ children }) => (
    <h6 className="mt-2 mb-1 text-label font-semibold first:mt-0">
      {children}
    </h6>
  ),
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children, className }) => (
    <ul
      className={cn(
        "mb-2 list-disc pl-4.5 last:mb-0",
        className?.includes("contains-task-list") && "list-none pl-0",
      )}
    >
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal pl-4.5 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="my-0.5 marker:text-ink-muted">{children}</li>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold">{children}</strong>
  ),
  del: ({ children }) => <del className="text-ink-muted">{children}</del>,
  blockquote: ({ children }) => (
    <blockquote className="mb-2 border-l-2 border-line-control pl-2.5 text-ink-muted last:mb-0">
      {children}
    </blockquote>
  ),
  pre: CodeBlock,
  hr: () => <hr className="my-3 border-line" />,
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto last:mb-0">
      <table className="w-full border-collapse text-label font-normal">
        {children}
      </table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-b border-line-control py-1 pr-4 text-left align-bottom font-medium text-ink-muted">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-line py-1.5 pr-4 align-top">{children}</td>
  ),
  input: ({ checked }) => (
    <input
      type="checkbox"
      checked={checked}
      readOnly
      disabled
      className="mr-1.5 align-middle accent-(--accent)"
    />
  ),
};

/** A report reads at a larger size than a chat message, with anchored sections. */
const REPORT: Components = {
  h1: ({ children }) => (
    <h1 className="mb-4 text-[24px]/8 font-semibold tracking-[-0.015em] text-balance">
      {children}
    </h1>
  ),
  h2: ({ children, id }) => (
    <h2
      id={id}
      className="mt-9 mb-3 scroll-mt-4 text-[17px]/6 font-semibold first:mt-0"
    >
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-5 mb-2 text-[14px]/5 font-semibold">{children}</h3>
  ),
  p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
  details: ({ children, open }) => (
    <details
      open={open}
      data-report-section
      className="my-5 rounded-lg border border-line px-4 pb-3 open:pb-4 [&>summary_h2]:my-0 [&>summary_h2]:inline [&>summary_h2]:text-[15px]/6"
    >
      {children}
    </details>
  ),
  summary: ({ children }) => (
    <summary className="cursor-pointer py-3 text-ink marker:text-ink-muted">
      {children}
    </summary>
  ),
};

function escape(name: string): string {
  return name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * A remark plugin that links each evidence file the prose names by its path or bare file name, the way the server
 * decides a file is cited, so every file the report names opens in place.
 */
function linkEvidence(names: string[]) {
  const sorted = [...names].sort((a, b) => b.length - a.length).map(escape);
  const pattern = sorted.length
    ? new RegExp(
        `(?<![\\w./-])(?:evidence/)?(?:${sorted.join("|")})(?![\\w/-])`,
        "g",
      )
    : null;
  const visit = (node: MdNode) => {
    if (!pattern || !node.children || node.type === "link") {
      return;
    }
    node.children = node.children.flatMap((child): MdNode[] => {
      if (child.type !== "text" || !child.value) {
        visit(child);
        return [child];
      }
      const parts: MdNode[] = [];
      let last = 0;
      for (const match of child.value.matchAll(pattern)) {
        const at = match.index ?? 0;
        if (at > last) {
          parts.push({ type: "text", value: child.value.slice(last, at) });
        }
        parts.push({
          type: "link",
          url: match[0],
          children: [{ type: "text", value: match[0] }],
        });
        last = at + match[0].length;
      }
      if (last === 0) {
        return [child];
      }
      if (last < child.value.length) {
        parts.push({ type: "text", value: child.value.slice(last) });
      }
      return parts;
    });
  };
  return () => (tree: MdNode) => visit(tree);
}

/** What an agent wrote, rendered as Markdown with GitHub's extensions; raw HTML in it is left out. */
export function Markdown({
  children,
  className,
  onEvidence,
  resolve,
  evidenceNames,
  renderImage,
  report = false,
}: {
  children: string;
  className?: string;
  /** Report typography: larger headings, ## headings anchored for the outline. */
  report?: boolean;
  /** Opens an evidence file in the app instead of following a link. */
  onEvidence?: (path: string) => void;
  /** The evidence file a link, a code span, or a name in the text stands for, if any. */
  resolve?: (text: string) => string | null;
  /** The evidence folder's files by their names inside it, which the text links wherever it names one. */
  evidenceNames?: string[];
  /** Render only images resolved against the check's evidence listing. */
  renderImage?: (source: string, caption: string) => ReactNode;
}) {
  const root = useRef<HTMLDivElement>(null);
  const collapsible =
    report &&
    indexReport(children).headings.some(
      (heading) => heading.defaultOpen !== undefined,
    );
  const components = useMemo<Components>(
    () => ({
      ...BASE,
      a: makeLink(onEvidence, resolve),
      img: ({ src, alt }) =>
        (typeof src === "string" ? renderImage?.(src, alt ?? "") : null) ?? (
          <span className="text-ink-muted">{alt || "Image unavailable"}</span>
        ),
      ...(report ? REPORT : {}),
      code: ({ children, className: language, node }) => {
        const inline = node?.position?.start.line === node?.position?.end.line;
        const value = typeof children === "string" ? children : "";
        const path =
          !language && inline && resolve && onEvidence ? resolve(value) : null;
        if (path && onEvidence) {
          return (
            <button
              type="button"
              onClick={() => onEvidence(path)}
              title={`Open ${path}`}
              className="rounded-sm border border-line bg-field px-1 text-left mono-value wrap-anywhere text-accent-ink underline decoration-accent-ink/40 underline-offset-2 hover:border-line-control hover:decoration-accent-ink"
            >
              {children}
            </button>
          );
        }
        return (
          <code
            className={cn(
              "rounded-sm border border-line bg-field px-1 mono-value wrap-anywhere",
              language,
            )}
          >
            {children}
          </code>
        );
      },
    }),
    [onEvidence, resolve, report, renderImage],
  );
  const plugins = useMemo(
    () => [
      remarkGfm,
      ...(report ? [reportSections] : []),
      ...(evidenceNames?.length && onEvidence
        ? [linkEvidence(evidenceNames)]
        : []),
    ],
    [evidenceNames, onEvidence, report],
  );
  return (
    <div
      ref={root}
      className={cn("min-w-0 wrap-break-word text-ink", className)}
    >
      {collapsible && (
        <div className="mb-4 flex gap-1">
          <Button
            size="sm"
            onClick={() =>
              root.current && setReportSections(root.current, true)
            }
          >
            Expand all
          </Button>
          <Button
            size="sm"
            onClick={() =>
              root.current && setReportSections(root.current, false)
            }
          >
            Collapse all
          </Button>
        </div>
      )}
      <ReactMarkdown
        key={children}
        remarkPlugins={plugins}
        components={components}
        skipHtml
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
