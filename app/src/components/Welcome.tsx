import { useState } from "react";

import { Button } from "@/components/ui/button";
import { CropMarks } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { copyText } from "@/lib/utils";

const PROMPTS = [
  "Use reality-check to check that a new user can sign up and send a message on http://localhost:3000",
  "I fixed the export bug. Use reality-check to check it as a user would before you say it is done.",
  "Use reality-check to try our checkout on a phone-sized screen with a slow network, and tell me what gets in the way.",
  "Before we share the docs site, use reality-check to click through it like a first-time visitor.",
];

function Prompt({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <li className="flex items-start gap-3 rounded-md border border-line bg-panel py-2.5 pr-2 pl-3">
      <p className="min-w-0 flex-1">{text}</p>
      <Button
        variant="secondary"
        size="sm"
        aria-label={copied ? "Copied" : "Copy this prompt"}
        title={copied ? "Copied" : "Copy this prompt"}
        onClick={() =>
          void copyText(text).then((done) => {
            setCopied(done);
            setTimeout(() => setCopied(false), 1500);
          })
        }
      >
        <Icon name={copied ? "check" : "copy"} />
        {copied ? "Copied" : "Copy"}
      </Button>
    </li>
  );
}

/** With no checks yet: when to run one, what happens then, and prompts to give an agent. */
export function Welcome() {
  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col gap-6 px-6 py-10 max-sm:px-4 max-sm:py-6">
      <div className="relative flex flex-col gap-3 px-6 pt-8 pb-6 max-sm:px-4">
        <CropMarks />
        <div className="grid size-12 place-items-center rounded-lg bg-pastel-rose text-on-pastel">
          <Icon name="eye" size={24} />
        </div>
        <h1 className="text-display max-sm:text-[22px]/7">No checks yet</h1>
        <p className="text-[14px]/[22px] text-ink-muted">
          Run a check when your agent says something works and you want to see
          it work the way a person would use it: after a fix, before a demo, or
          before you share it.
        </p>
        <p className="text-[14px]/[22px] text-ink-muted">
          Ask your agent to use Reality Check. Its own agent opens the software,
          uses it like a person, saves screenshots and other evidence, and
          writes a report of what worked and what did not. The check shows here
          while it runs, and stays here with its report.
        </p>
      </div>
      <section className="flex flex-col gap-2.5">
        <h2 className="text-label">Ask your agent</h2>
        <ul className="flex flex-col gap-2">
          {PROMPTS.map((text) => (
            <Prompt key={text} text={text} />
          ))}
        </ul>
      </section>
      <p className="flex items-start gap-2 text-caption text-ink-muted">
        <Icon name="warning" className="mt-px" />
        Not for release gates or CI: keep scripted tests there.
      </p>
    </div>
  );
}
