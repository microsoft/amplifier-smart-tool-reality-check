## Writing the report

Write for a person who wants to know what happened without reading the agent's activity.
Use a short, descriptive `#` title, then two or three sentences with the main result and any
important coverage limits. Keep the report concise: short paragraphs and bullets, no activity
transcript or repeated findings. Put lengthy logs and technical records in evidence files and
link to them. Do not omit requested coverage to meet a length target.

Use these exact `##` headings, in this order. The app uses them to show expandable sections:

- `## Needs attention`: confirmed failures first, each under a descriptive `###` heading.
  State the user impact, action, expected result, and what was recorded. Link supporting
  evidence. Say explicitly when no failures were found, or when the check could not establish
  a result. A completed run does not mean the software passed.
- `## Observations`: usability concerns, warnings, and open questions, separate from failures.
  Distinguish observed facts from hypotheses. Say when there are none.
- `## What was checked`: a compact list of the requested items with pass, fail, or not checked,
  evidence links, and reasons for gaps. Identify browser/device differences where they matter.
  A result without recorded evidence is not checked, never a pass.
- `## Next steps`: concise guidance to the calling agent, tied to the findings. Say what it
  could investigate or fix, what evidence to start from, and what to recheck after a change.
  These are suggested actions, not instructions for a person to copy and paste and not
  authorization to change scope or user data. Do not present an untested cause as a known fix.
  If no action is needed, say so.
- `## Run details`: environment, methods, recording limits, and cleanup, including anything
  left running and the command that stops it. Put important limits in the opening summary too.

Embed one or two useful screenshots near the findings they support with ordinary Markdown,
such as `![Selected filters disagree with the displayed results](evidence/03-after-back.png)`.
Use descriptive alt text as a short caption. Choose screenshots that show the actual result,
not incidental setup, and link other evidence instead of embedding a gallery. Only embed files
recorded in this check's evidence folder; do not embed remote images or fabricate screenshots.
When screenshots are not appropriate, use a short recorded excerpt or a link to the relevant
request, console message, or timing instead.
