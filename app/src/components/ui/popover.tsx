import { Popover as PopoverPrimitive } from "@base-ui/react/popover";
import type { ReactNode } from "react";

import { POPUP } from "@/components/ui/popup";
import { cn } from "@/lib/utils";

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverClose = PopoverPrimitive.Close;

/** The open popover, placed against its trigger. */
export function PopoverContent({
  side = "bottom",
  align = "end",
  label,
  className,
  children,
}: {
  side?: "top" | "bottom" | "left" | "right";
  align?: "start" | "center" | "end";
  label?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Positioner
        side={side}
        align={align}
        sideOffset={4}
        collisionPadding={8}
        className="z-50 outline-none"
      >
        <PopoverPrimitive.Popup
          aria-label={label}
          className={cn(POPUP, className)}
        >
          {children}
        </PopoverPrimitive.Popup>
      </PopoverPrimitive.Positioner>
    </PopoverPrimitive.Portal>
  );
}
