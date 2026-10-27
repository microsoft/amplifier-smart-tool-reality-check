import type { IconName } from "@/components/ui/icon";
import type { EvidenceEntry } from "@/lib/api";

export type EvidenceKind =
  "screenshot" | "video" | "network" | "data" | "script" | "text";

/** An evidence file with what the view needs to show it: its name in the folder, extension, and kind. */
export type Evidence = EvidenceEntry & {
  /** Its path inside the evidence folder, such as `01-home.png`. */
  name: string;
  ext: string;
  kind: EvidenceKind;
};

/** What the evidence page shows: one kind or all, and names containing a query. */
export type EvidenceFilter = { kind: "all" | EvidenceKind; query: string };

export const DEFAULT_FILTER: EvidenceFilter = { kind: "all", query: "" };

export const KIND_LABELS: Record<EvidenceKind, string> = {
  screenshot: "Screenshots",
  video: "Videos",
  network: "Network",
  data: "Data",
  script: "Scripts",
  text: "Text and logs",
};

export const KIND_ICONS: Record<EvidenceKind, IconName> = {
  screenshot: "image",
  video: "play",
  network: "globe",
  data: "braces",
  script: "code",
  text: "terminal",
};

export const KINDS = Object.keys(KIND_LABELS) as EvidenceKind[];

const IMAGE = /^(png|jpe?g|webp|gif|bmp|avif)$/;
const VIDEO = /^(mp4|webm)$/;
const SCRIPT = /^(py|js|mjs|cjs|ts|sh|ps1|bash)$/;
const DATA = /^(json|jsonl|ndjson|csv|yaml|yml|xml)$/;

function kindOf(ext: string, mediaType: string): EvidenceKind {
  if (IMAGE.test(ext) && mediaType.startsWith("image/")) {
    return "screenshot";
  }
  if (VIDEO.test(ext)) {
    return "video";
  }
  if (ext === "har") {
    return "network";
  }
  if (SCRIPT.test(ext)) {
    return "script";
  }
  return DATA.test(ext) ? "data" : "text";
}

export function toEvidence(entry: EvidenceEntry): Evidence {
  const name = entry.path.replace(/^evidence\//, "");
  const base = name.split("/").at(-1) ?? name;
  const dot = base.lastIndexOf(".");
  const ext = dot > 0 ? base.slice(dot + 1).toLowerCase() : "";
  return { ...entry, name, ext, kind: kindOf(ext, entry.media_type) };
}

export function isImage(item: Evidence): boolean {
  return item.kind === "screenshot";
}

/** Evidence in the order the report first names each file, then the rest as the folder lists them. */
export function reportOrder(
  report: string | null,
  evidence: Evidence[],
): Evidence[] {
  const byPath = new Map(evidence.map((item) => [item.path, item]));
  const seen = new Set<string>();
  if (report) {
    const resolve = resolver(evidence);
    for (const match of report.matchAll(
      /evidence\/[^\s)`'"\],]+|[\w./-]+\.\w{1,6}/g,
    )) {
      const path = resolve(match[0].replace(/[.,;:]+$/, ""));
      if (path) {
        seen.add(path);
      }
    }
  }
  for (const item of evidence) {
    seen.add(item.path);
  }
  return [...seen].flatMap((path) => byPath.get(path) ?? []);
}

/**
 * The evidence file a name in the report stands for: a path under evidence/, a path inside the evidence folder, or a
 * file name only one file has. Agents often cite a file by its bare name, such as `02-desktop-home.png`.
 */
export function resolver(
  evidence: Evidence[],
): (text: string) => string | null {
  const paths = new Set(evidence.map((item) => item.path));
  const byName = new Map<string, string[]>();
  for (const item of evidence) {
    const base = item.name.split("/").at(-1) ?? item.name;
    byName.set(base, [...(byName.get(base) ?? []), item.path]);
  }
  return (text) => {
    let token = text.trim().replace(/^\.\//, "");
    try {
      token = decodeURIComponent(token);
    } catch {
      // Not percent-encoded, so it is taken as written.
    }
    if (paths.has(token)) {
      return token;
    }
    if (paths.has(`evidence/${token}`)) {
      return `evidence/${token}`;
    }
    const named = byName.get(token);
    return named && named.length === 1 ? named[0] : null;
  };
}
