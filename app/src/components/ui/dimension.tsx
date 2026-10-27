import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A horizontal dimension line, ticked at each end with its label in the middle, as a technical drawing marks a size. */
export function Dimension({
  children,
  tone = "accent",
  className,
}: {
  children: ReactNode;
  tone?: "accent" | "control";
  className?: string;
}) {
  const line = tone === "accent" ? "border-accent-ink" : "border-line-control";
  return (
    <div
      className={cn(
        "flex min-w-0 items-center gap-2",
        tone === "accent" ? "text-accent-ink" : "text-ink-muted",
        className,
      )}
    >
      <span className={cn("h-2 flex-1 border-t border-l", line)} />
      <span className="mono-annotation whitespace-nowrap">{children}</span>
      <span className={cn("h-2 flex-1 border-t border-r", line)} />
    </div>
  );
}
