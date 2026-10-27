import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
/** What the person picked: System follows the host's theme, else the computer's. */
export type ThemePreference = "system" | Theme;

const STORAGE_NAME = "reality-check.theme";
const darkScheme = window.matchMedia("(prefers-color-scheme: dark)");
const listeners = new Set<() => void>();
let hostTheme: Theme | null = null;
let preference: ThemePreference = read();

function read(): ThemePreference {
  try {
    const saved = localStorage.getItem(STORAGE_NAME);
    return saved === "light" || saved === "dark" ? saved : "system";
  } catch {
    return "system";
  }
}

/** The theme the view shows: the person's pick, or for System the host's, else the computer's. */
export function effectiveTheme(): Theme {
  if (preference !== "system") {
    return preference;
  }
  return hostTheme ?? (darkScheme.matches ? "dark" : "light");
}

function apply() {
  const theme = effectiveTheme();
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  for (const listener of listeners) {
    listener();
  }
}

/** Record the theme the host gives, which System follows. */
export function setHostTheme(theme: Theme) {
  hostTheme = theme;
  apply();
}

export function setThemePreference(next: ThemePreference) {
  preference = next;
  try {
    localStorage.setItem(STORAGE_NAME, next);
  } catch {
    // A host that blocks storage keeps the pick until the view reloads.
  }
  apply();
}

darkScheme.addEventListener("change", apply);
apply();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useThemePreference(): ThemePreference {
  return useSyncExternalStore(subscribe, () => preference);
}
