import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";
import type { ReactElement, ReactNode } from "react";

import { Kbd } from "@/components/ui/kbd";

export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <TooltipPrimitive.Provider delay={500} closeDelay={0}>
      {children}
    </TooltipPrimitive.Provider>
  );
}

/** A short name for a control, and the key that does the same, shown on hover and keyboard focus. */
export function Tooltip({
  content,
  keys,
  side = "bottom",
  children,
}: {
  content: ReactNode;
  keys?: string;
  side?: "top" | "bottom" | "left" | "right";
  children: ReactElement;
}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger render={children} />
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Positioner
          side={side}
          sideOffset={6}
          collisionPadding={8}
          className="z-60"
        >
          <TooltipPrimitive.Popup className="flex max-w-72 items-center gap-1.5 rounded-md bg-raised px-2 py-1 text-caption text-ink shadow-popover transition-opacity data-ending-style:opacity-0 data-starting-style:opacity-0">
            {content}
            {keys && <Kbd>{keys}</Kbd>}
          </TooltipPrimitive.Popup>
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
