import { useRef, useState, type ReactNode } from "react";
import { Group, Panel, type Layout } from "react-resizable-panels";

import { ResizeHandle } from "@/components/ui/resizable";
import type { AppLayout } from "@/lib/layout";

// Only small floors, so no pane can be dragged away by accident; there are no ceilings. Closing is the toggle's job.
const MIN = { sidebar: 160, canvas: 280, activity: 240 };

/** Where the panes start: as the person left them, in pixels, as percentages of the width there is now. */
function startingLayout(layout: AppLayout, width: number): Layout | undefined {
  if (width <= 0) {
    return undefined;
  }
  const share = (pixels: number) => (pixels / width) * 100;
  const sidebar = layout.sidebar.open ? share(layout.sidebar.size) : 0;
  const activity = layout.activity.open ? share(layout.activity.size) : 0;
  const canvas = Math.max(share(MIN.canvas), 100 - sidebar - activity);
  const result: Layout = { canvas };
  if (layout.sidebar.open) {
    result.sidebar = sidebar;
  }
  if (layout.activity.open) {
    result.activity = activity;
  }
  return result;
}

/**
 * Checks, then the report canvas, then Activity on the right. Every pane resizes freely down to a small
 * floor; a closed pane is not rendered, so it comes back at the width it had.
 */
export function Workspace({
  layout,
  width,
  sidebar,
  canvas,
  activity,
  onResized,
}: {
  layout: AppLayout;
  width: number;
  sidebar: ReactNode;
  canvas: ReactNode;
  activity: ReactNode;
  /** Each open side pane's width in pixels after the person drags a handle. */
  onResized: (widths: { sidebar?: number; activity?: number }) => void;
}) {
  // Read once: the group takes its layout from here only as it mounts; App remounts it when a pane opens or closes.
  const [start] = useState(() => startingLayout(layout, width));
  const group = useRef<HTMLDivElement>(null);
  return (
    <Group
      orientation="horizontal"
      defaultLayout={start}
      elementRef={group}
      onLayoutChanged={(changed, meta) => {
        if (!meta.isUserInteraction) {
          return;
        }
        const room = group.current?.offsetWidth ?? 0;
        const pixels = (id: string) =>
          changed[id] === undefined
            ? undefined
            : Math.round((changed[id] / 100) * room);
        onResized({ sidebar: pixels("sidebar"), activity: pixels("activity") });
      }}
      className="min-h-0 flex-1"
    >
      {layout.sidebar.open && (
        <>
          <Panel
            id="sidebar"
            minSize={MIN.sidebar}
            groupResizeBehavior="preserve-pixel-size"
            className="h-full overflow-hidden"
          >
            {sidebar}
          </Panel>
          <ResizeHandle label="Resize checks" />
        </>
      )}
      <Panel
        id="canvas"
        minSize={MIN.canvas}
        className="h-full overflow-hidden"
      >
        {canvas}
      </Panel>
      {layout.activity.open && (
        <>
          <ResizeHandle label="Resize activity" />
          <Panel
            id="activity"
            minSize={MIN.activity}
            groupResizeBehavior="preserve-pixel-size"
            className="h-full overflow-hidden"
          >
            {activity}
          </Panel>
        </>
      )}
    </Group>
  );
}
