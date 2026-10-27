import { createContext, useContext } from "react";

import type { CheckReference } from "@/lib/api";
import type { Nav, Route } from "@/lib/nav";
import type { Check } from "@/lib/store";

export type Ui = {
  check: Check | null;
  nav: Nav;
  navigate: (route: Route) => void;
  replaceRoute: (route: Route) => void;
  goBack: () => void;
  goForward: () => void;
  /** Opens an evidence file over the canvas; prev and next move through `list`, or every file when absent. */
  openEvidence: (path: string, list?: string[]) => void;
  /** Scrolls Activity to the step behind an evidence file, or to a step by key, and marks it for a moment. */
  showInActivity: (target: { path?: string; step?: string }) => void;
  /** Brings the report forward and marks it for a moment. */
  focusReport: () => void;
  /** Shows another check, as a link to it from this one does. */
  selectCheck: (ref: CheckReference) => void;
  toast: (text: string) => void;
};

export const UiContext = createContext<Ui | null>(null);

export function useUi(): Ui {
  const ui = useContext(UiContext);
  if (!ui) {
    throw new Error("useUi outside UiContext");
  }
  return ui;
}
