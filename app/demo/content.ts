/** How one thing the example checked came out, as the report says. */
export type Outcome = "passed" | "failed" | "skipped";

/** The screenshots under the report: one for each thing that was checked. */
export type Gallery = {
  title: string;
  items: { evidence: string; label: string; outcome: Outcome }[];
};

/** The example's own words, from the `content` of its section in site/site.yaml. */
export type Content = { request: string; report: string; gallery: Gallery };

const OUTCOMES: readonly string[] = ["passed", "failed", "skipped"];

function text(value: unknown, where: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${where} in content.json is not text.`);
  }
  return value;
}

/** `value` as the example's content, or an error that names the first part that is wrong. */
export function parseContent(value: unknown): Content {
  const content = (value ?? {}) as Record<string, unknown>;
  const gallery = (content.gallery ?? {}) as Record<string, unknown>;
  if (!Array.isArray(gallery.items)) {
    throw new Error("gallery.items in content.json is not a list.");
  }
  return {
    request: text(content.request, "request"),
    report: text(content.report, "report"),
    gallery: {
      title: text(gallery.title, "gallery.title"),
      items: gallery.items.map((each: Record<string, unknown>, index) => {
        const where = `gallery.items[${index}]`;
        if (!OUTCOMES.includes(each?.outcome as string)) {
          throw new Error(
            `${where}.outcome in content.json is not one of ${OUTCOMES.join(", ")}.`,
          );
        }
        return {
          evidence: text(each.evidence, `${where}.evidence`),
          label: text(each.label, `${where}.label`),
          outcome: each.outcome as Outcome,
        };
      }),
    },
  };
}
