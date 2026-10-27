import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export type MdNode = {
  type: string;
  value?: string;
  url?: string;
  alt?: string;
  depth?: number;
  children?: MdNode[];
  data?: {
    hName?: string;
    hProperties?: Record<string, string | boolean>;
  };
};

type ReportHeading = {
  id: string;
  text: string;
  defaultOpen?: boolean;
};

/** What the app reads from a report beyond rendering it: its title and its outline. */
export type ReportIndex = {
  title: string | null;
  headings: ReportHeading[];
};

const SECTIONS = new Map([
  ["Needs attention", true],
  ["Observations", false],
  ["What was checked", false],
  ["Next steps", true],
  ["Run details", false],
]);

/** A heading's anchor: lowercase words joined by dashes. */
export function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-|-$/g, "");
}

function textOf(node: MdNode): string {
  return node.value ?? node.alt ?? node.children?.map(textOf).join("") ?? "";
}

function headings(tree: MdNode): { node: MdNode; heading: ReportHeading }[] {
  const used = new Set<string>();
  return (tree.children ?? [])
    .filter((node) => node.type === "heading" && node.depth === 2)
    .map((node) => {
      const text = textOf(node).trim();
      const base = slug(text);
      let id = base;
      let suffix = 1;
      while (used.has(id)) {
        id = `${base}-${suffix++}`;
      }
      used.add(id);
      return {
        node,
        heading: { id, text, defaultOpen: SECTIONS.get(text) },
      };
    });
}

/** Group only recognized top-level sections, leaving older and unknown report content intact. */
export function reportSections() {
  return (tree: MdNode) => {
    const indexed = new Map(
      headings(tree).map(({ node, heading }) => [node, heading]),
    );
    const children: MdNode[] = [];
    let section: MdNode | null = null;
    for (const node of tree.children ?? []) {
      if (node.type === "heading" && (node.depth ?? 0) <= 2) {
        section = null;
      }
      const heading = indexed.get(node);
      if (heading) {
        node.data = {
          ...node.data,
          hProperties: { ...node.data?.hProperties, id: heading.id },
        };
        if (heading.defaultOpen !== undefined) {
          section = {
            type: "reportSection",
            data: {
              hName: "details",
              hProperties: {
                open: heading.defaultOpen,
                "data-report-section": true,
              },
            },
            children: [
              {
                type: "reportSummary",
                data: { hName: "summary" },
                children: [node],
              },
            ],
          };
          children.push(section);
          continue;
        }
      }
      if (section) {
        section.children?.push(node);
      } else {
        children.push(node);
      }
    }
    tree.children = children;
  };
}

const cache = new Map<string, ReportIndex>();

export function indexReport(markdown: string | null): ReportIndex {
  if (!markdown) {
    return { title: null, headings: [] };
  }
  const known = cache.get(markdown);
  if (known) {
    return known;
  }
  let index: ReportIndex = { title: null, headings: [] };
  // Use the renderer's parser so outlines and sections agree on Markdown syntax.
  ReactMarkdown({
    children: markdown,
    remarkPlugins: [
      remarkGfm,
      () => (tree: MdNode) => {
        const title = tree.children?.find(
          (node) => node.type === "heading" && node.depth === 1,
        );
        index = {
          title: title ? textOf(title).trim() : null,
          headings: headings(tree).map(({ heading }) => heading),
        };
      },
    ],
    allowedElements: [],
  });
  cache.set(markdown, index);
  return index;
}

export function setReportSections(root: ParentNode, open: boolean): void {
  root
    .querySelectorAll<HTMLDetailsElement>("details[data-report-section]")
    .forEach((section) => {
      section.open = open;
    });
}

/** Open a heading's section before scrolling, including headings inside its summary. */
export function revealReportHeading(root: ParentNode, id: string): void {
  const heading = Array.from(root.querySelectorAll<HTMLElement>("[id]")).find(
    (element) => element.id === id,
  );
  if (!heading) {
    return;
  }
  let section = heading.closest("details");
  while (section) {
    section.open = true;
    section = section.parentElement?.closest("details") ?? null;
  }
  heading.scrollIntoView({ behavior: "smooth", block: "start" });
}
