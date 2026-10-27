import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import type { ReactNode, RefObject } from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { cn } from "@/lib/utils";

export const Dialog = DialogPrimitive.Root;

/** A dialog over a scrim, with its title and a close button on top; it fills the view under 640px. */
export function DialogContent({
  title,
  subtitle,
  initialFocus,
  keepMounted = false,
  className,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  initialFocus?: RefObject<HTMLElement | null>;
  /** Keeps what is in it, such as a draft, while it is closed. */
  keepMounted?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <DialogPrimitive.Portal keepMounted={keepMounted}>
      <DialogPrimitive.Backdrop className="fixed inset-0 z-50 bg-scrim transition-opacity data-ending-style:opacity-0 data-starting-style:opacity-0" />
      <DialogPrimitive.Viewport className="fixed inset-0 z-50 flex items-center justify-center sm:p-6">
        <DialogPrimitive.Popup
          initialFocus={initialFocus}
          className={cn(
            "flex max-h-full w-full flex-col overflow-hidden bg-raised text-ink shadow-popover transition-[opacity,scale] outline-none data-ending-style:scale-98 data-ending-style:opacity-0 data-starting-style:scale-98 data-starting-style:opacity-0 max-sm:h-full sm:rounded-lg",
            className,
          )}
        >
          <header className="flex shrink-0 items-start gap-3 border-b border-line py-3.5 pr-3 pl-5">
            <div className="min-w-0 flex-1">
              <DialogPrimitive.Title className="text-title">
                {title}
              </DialogPrimitive.Title>
              {subtitle && (
                <DialogPrimitive.Description className="truncate mono-annotation text-ink-muted">
                  {subtitle}
                </DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close render={<Button icon aria-label="Close" />}>
              <Icon name="close" size={20} />
            </DialogPrimitive.Close>
          </header>
          {children}
        </DialogPrimitive.Popup>
      </DialogPrimitive.Viewport>
    </DialogPrimitive.Portal>
  );
}
