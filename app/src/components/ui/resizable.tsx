import { Separator } from "react-resizable-panels";

/**
 * The handle between two panes: a hairline at rest, accent ink with a square grip while hovered, dragged, or focused.
 * Double-click puts the pane back to its default size; arrow keys resize it when focused.
 */
export function ResizeHandle({ label }: { label: string }) {
  return (
    <Separator
      aria-label={label}
      className="group/handle relative z-10 w-px shrink-0 bg-line outline-none data-[separator=active]:bg-accent-ink data-[separator=active]:shadow-[0_0_0_1px_var(--accent-ink)] data-[separator=focus]:bg-accent-ink data-[separator=focus]:shadow-[0_0_0_1px_var(--accent-ink)] data-[separator=hover]:bg-accent-ink data-[separator=hover]:shadow-[0_0_0_1px_var(--accent-ink)]"
    >
      <span className="absolute top-1/2 -left-0.75 hidden size-1.75 -translate-y-1/2 border border-accent-ink bg-panel group-data-[separator=active]/handle:block group-data-[separator=focus]/handle:block group-data-[separator=hover]/handle:block" />
    </Separator>
  );
}
