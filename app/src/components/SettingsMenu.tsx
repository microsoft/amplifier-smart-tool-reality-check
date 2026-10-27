import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Kbd } from "@/components/ui/kbd";
import {
  Popover,
  PopoverClose,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Segmented } from "@/components/ui/segmented";
import { Tooltip } from "@/components/ui/tooltip";
import { REPOSITORY, VERSION } from "@/lib/brand";
import { openLink } from "@/lib/host";
import { setThemePreference, useThemePreference } from "@/lib/theme";

const ROW =
  "flex h-7 w-full cursor-default items-center gap-2 rounded-sm px-2 text-left whitespace-nowrap hover:bg-hover";

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 px-2 pt-2 pb-2.5">
      <p className="text-label text-ink-muted">{label}</p>
      {children}
    </div>
  );
}

/** The app's own settings, kept in this view's storage: theme and layout; plus its shortcuts, docs, and version. */
export function SettingsMenu({
  onShortcuts,
  onResetLayout,
}: {
  onShortcuts: () => void;
  onResetLayout: () => void;
}) {
  const theme = useThemePreference();
  return (
    <Popover>
      <Tooltip content="Settings">
        <PopoverTrigger
          render={<Button size="sm" icon aria-label="Settings" />}
        >
          <Icon name="gear" />
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent
        label="Settings"
        className="max-h-[calc(100dvh-64px)] w-72 max-w-[calc(100vw-16px)] overflow-y-auto"
      >
        <Section label="Appearance">
          <Segmented
            label="Theme"
            size="sm"
            full
            value={theme}
            onChange={setThemePreference}
            options={[
              { value: "system", label: "System", icon: "monitor" },
              { value: "light", label: "Light", icon: "sun" },
              { value: "dark", label: "Dark", icon: "moon" },
            ]}
          />
        </Section>
        <hr className="-mx-1 my-1 border-line" />
        <PopoverClose className={ROW} onClick={onShortcuts}>
          <span className="flex-1">Keyboard shortcuts</span>
          <Kbd>?</Kbd>
        </PopoverClose>
        <PopoverClose className={ROW} onClick={onResetLayout}>
          Reset layout
        </PopoverClose>
        {REPOSITORY && (
          <PopoverClose
            className={ROW}
            onClick={() => REPOSITORY && openLink(REPOSITORY)}
          >
            <span className="flex-1">Documentation</span>
            <Icon name="link-out" className="text-ink-muted" />
          </PopoverClose>
        )}
        <hr className="-mx-1 my-1 border-line" />
        <p className="flex h-6 items-center px-2 mono-annotation text-ink-muted">
          Reality Check{VERSION && ` ${VERSION}`}
        </p>
      </PopoverContent>
    </Popover>
  );
}
