/** Where the canvas is: the report, its evidence, or the check's details, with a file opened over any of them. */
export type Page =
  { kind: "report" } | { kind: "evidence" } | { kind: "details" };

export type Route =
  Page | { kind: "file"; path: string; list: string[]; from: Page };

/** The canvas's history for one check, like a browser's: back, where it is, and forward. */
export type Nav = { back: Route[]; current: Route; forward: Route[] };

export const START: Nav = {
  back: [],
  current: { kind: "report" },
  forward: [],
};

function same(a: Route, b: Route): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function push(nav: Nav, route: Route): Nav {
  if (same(nav.current, route)) {
    return nav;
  }
  return {
    back: [...nav.back, nav.current].slice(-50),
    current: route,
    forward: [],
  };
}

/** Swaps where it is without adding a step, as stepping between files does. */
export function replace(nav: Nav, route: Route): Nav {
  return { ...nav, current: route };
}

/** One step back; with no history, up to the parent page. */
export function back(nav: Nav): Nav {
  const previous = nav.back.at(-1);
  if (previous) {
    return {
      back: nav.back.slice(0, -1),
      current: previous,
      forward: [nav.current, ...nav.forward],
    };
  }
  const up = parentOf(nav.current);
  return up
    ? { back: [], current: up, forward: [nav.current, ...nav.forward] }
    : nav;
}

export function forward(nav: Nav): Nav {
  const next = nav.forward[0];
  return next
    ? {
        back: [...nav.back, nav.current],
        current: next,
        forward: nav.forward.slice(1),
      }
    : nav;
}

export function parentOf(route: Route): Page | null {
  if (route.kind === "file") {
    return route.from;
  }
  return route.kind === "report" ? null : { kind: "report" };
}

/** The page under the current route: the route itself, or for a file, the page it was opened from. */
export function pageOf(route: Route): Page {
  return route.kind === "file" ? route.from : route;
}

/** The trail from the report down to where it is. */
export function trail(route: Route): Route[] {
  const crumbs: Route[] = [];
  let at: Route | null = route;
  while (at) {
    crumbs.unshift(at);
    at = parentOf(at);
  }
  return crumbs;
}
