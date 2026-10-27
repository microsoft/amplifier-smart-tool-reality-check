import assert from "node:assert/strict";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  ReportMarkdown,
  Source,
} from "../src/components/canvas/ReportPage.tsx";
import { Markdown } from "../src/components/ui/markdown.tsx";
import { toEvidence } from "../src/lib/evidence.ts";
import {
  indexReport,
  revealReportHeading,
  setReportSections,
} from "../src/lib/report.ts";
import { UiContext } from "../src/lib/ui.ts";

const report = `# Checkout report

The checkout needs a fix.

## Needs attention
The payment button did not respond.

## Observations
The page loaded.

### A closer look
The form was visible.

## What was checked
Checkout.

## Next steps
Fix the button.

## Run details
Browser session.

## Additional context
This stays visible.
`;

function renderReport(markdown) {
  return renderToStaticMarkup(
    createElement(Markdown, { report: true }, markdown),
  );
}

test("known sections use the required defaults without hiding the summary or unknown sections", () => {
  const html = renderReport(report);
  const sections = [...html.matchAll(/<details([^>]*)>(.*?)<\/details>/gs)];
  assert.equal(sections.length, 5);
  assert.deepEqual(
    sections.map(([, attributes, body]) => ({
      title: /<h2[^>]*>(.*?)<\/h2>/.exec(body)?.[1],
      open: attributes.includes('open=""'),
    })),
    [
      { title: "Needs attention", open: true },
      { title: "Observations", open: false },
      { title: "What was checked", open: false },
      { title: "Next steps", open: true },
      { title: "Run details", open: false },
    ],
  );
  const visible = html.replace(/<details.*?<\/details>/gs, "");
  assert.match(visible, /Checkout report/);
  assert.match(visible, /The checkout needs a fix/);
  assert.match(visible, /This stays visible/);
  assert.match(html, /Expand all/);
  assert.match(html, /Collapse all/);
  assert.match(sections[1][2], /A closer look/);
});

test("the parser handles formatted and setext headings, duplicates, and fenced samples", () => {
  const markdown = `Report *title*
==============

\`\`\`md
## Needs attention
\`\`\`

> ## Observations

What was **checked**
--------------------

## [Next steps](https://example.com)
## Next steps
## Next steps-1
`;
  const index = indexReport(markdown);
  assert.equal(index.title, "Report title");
  assert.deepEqual(
    index.headings.map(({ id }) => id),
    ["what-was-checked", "next-steps", "next-steps-1", "next-steps-1-1"],
  );
  const html = renderReport(markdown);
  for (const heading of index.headings) {
    assert.ok(html.includes(`id="${heading.id}"`));
  }
  assert.equal((html.match(/<details/g) ?? []).length, 3);
});

test("older reports stay ordinary Markdown and a new title ends a section", () => {
  const older = renderReport(
    "# Result\nSummary.\n\n## Findings\nOne.\n\n## Evidence\nTwo.",
  );
  assert.doesNotMatch(older, /<details|Expand all|Collapse all/);
  assert.match(older, /id="findings"/);
  assert.match(older, /One/);
  const html = renderReport("## Observations\nInside.\n\n# Appendix\nOutside.");
  assert.match(html, /<\/details>\s*<h1[^>]*>Appendix<\/h1>\s*<p[^>]*>Outside/);
});

test("expand and collapse affect report sections; outline opens the destination before scrolling", () => {
  const sections = [{ open: true }, { open: false }];
  const root = {
    querySelectorAll(selector) {
      assert.equal(selector, "details[data-report-section]");
      return sections;
    },
  };
  setReportSections(root, true);
  assert.deepEqual(
    sections.map((section) => section.open),
    [true, true],
  );
  setReportSections(root, false);
  assert.deepEqual(
    sections.map((section) => section.open),
    [false, false],
  );

  const section = { open: false, parentElement: null };
  let scrolled = false;
  const heading = {
    id: "observations",
    closest: () => section,
    scrollIntoView() {
      assert.equal(section.open, true);
      scrolled = true;
    },
  };
  const outlineRoot = { querySelectorAll: () => [heading] };
  revealReportHeading(outlineRoot, "observations");
  assert.equal(scrolled, true);
  section.open = false;
  revealReportHeading(outlineRoot, "missing");
  assert.equal(section.open, false);
});

test("embedded evidence uses an authenticated image and a readable caption, never a remote URL", () => {
  const evidence = [
    toEvidence({
      path: "evidence/checkout screen.png",
      media_type: "image/png",
      size: 12,
      modified_at: "2026-10-27T00:00:00Z",
      referenced: true,
    }),
    toEvidence({
      path: "evidence/notes.txt",
      media_type: "text/plain",
      size: 12,
      modified_at: "2026-10-27T00:00:00Z",
      referenced: true,
    }),
  ];
  const markdown = `![The checkout form](evidence/checkout%20screen.png)

![Reference caption][screen]

[screen]: evidence/checkout%20screen.png

![Remote image](https://example.com/tracker.png)
![Missing image](evidence/missing.png)
![Not an image](evidence/notes.txt)
<img src="https://example.com/raw.png">
`;
  const html = renderToStaticMarkup(
    createElement(
      UiContext.Provider,
      { value: { openEvidence() {} } },
      createElement(
        ReportMarkdown,
        {
          check: {
            ref: { check_id: "check", checks_directory: "checks" },
            evidence,
          },
        },
        markdown,
      ),
    ),
  );
  assert.equal(
    (html.match(/title="Open checkout screen.png"/g) ?? []).length,
    2,
  );
  assert.match(html, /The checkout form/);
  assert.match(html, /Reference caption/);
  assert.doesNotMatch(html, /<p[^>]*>[^<]*<(?:div|figure)/);
  assert.match(html, /Remote image/);
  assert.match(html, /Missing image/);
  assert.doesNotMatch(html, /title="Open notes.txt"|<img|src=|example\.com/);
});

test("Source keeps the original Markdown", () => {
  const html = renderToStaticMarkup(
    createElement(Source, { markdown: report }),
  );
  assert.ok(html.includes(`>${report}</pre>`));
});
