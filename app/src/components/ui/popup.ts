/** The surface every popup sits on: raised, with the popover shadow, fading and scaling in from where it opens. */
export const POPUP =
  "origin-(--transform-origin) rounded-lg bg-raised p-1 text-ink shadow-popover outline-none transition-[opacity,scale] data-ending-style:scale-98 data-ending-style:opacity-0 data-starting-style:scale-98 data-starting-style:opacity-0";

/** A row in a menu or a select's list. */
export const ITEM =
  "flex h-7 cursor-default items-center gap-2 rounded-sm px-2 whitespace-nowrap outline-none select-none data-disabled:text-ink-faint data-highlighted:bg-hover";

export const SEPARATOR = "-mx-1 my-1 border-t border-line";

export const GROUP_LABEL =
  "flex h-6 items-center px-2 mono-annotation text-ink-muted";
