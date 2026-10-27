import { useEffect, useRef } from "react";

/** What a key does, by the key as `KeyboardEvent.key` names it, lowercased. */
export type Shortcuts = Record<string, () => void>;

/** Whether a key pressed in `target` belongs to it rather than to the app: typing, or a popup's own keys. */
function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return (
    target.isContentEditable ||
    target.closest(
      "input, textarea, select, [role=dialog], [role=menu], [role=listbox]",
    ) !== null
  );
}

/** Single keys that act on the app, only while focus is not in a field or a popup, so they never fight typing. */
export function useShortcuts(shortcuts: Shortcuts) {
  const latest = useRef(shortcuts);

  useEffect(() => {
    latest.current = shortcuts;
  });

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.ctrlKey ||
        event.metaKey ||
        event.altKey ||
        event.isComposing ||
        typing(event.target)
      ) {
        return;
      }
      const action = latest.current[event.key.toLowerCase()];
      if (action) {
        event.preventDefault();
        action();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
