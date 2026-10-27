import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A key to press, like F or Shift+Enter. */
export function Kbd({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <kbd
      className={cn(
        "inline-flex h-4 shrink-0 items-center rounded-sm border border-line-control bg-panel px-1 mono-annotation tracking-normal text-ink-muted",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
