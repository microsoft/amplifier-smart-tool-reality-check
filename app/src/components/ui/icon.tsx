import { cn } from "@/lib/utils";

// Line icons on a 24 grid, stroked at 1.5 with square caps and miter joins. A leading "f:" fills the path instead.
const PATHS = {
  add: ["M12 4v16M4 12h16"],
  "arrow-left": ["M19.5 12H4.5", "M11 5.5L4.5 12l6.5 6.5"],
  "arrow-right": ["M4.5 12h15", "M13 5.5l6.5 6.5-6.5 6.5"],
  braces: [
    "M9 3.5H7.5a2 2 0 0 0-2 2v4L3.5 12l2 2.5v4a2 2 0 0 0 2 2H9",
    "M15 3.5h1.5a2 2 0 0 1 2 2v4l2 2.5-2 2.5v4a2 2 0 0 1-2 2H15",
  ],
  code: ["M8 7l-5 5 5 5", "M16 7l5 5-5 5", "M13.5 4.5l-3 15"],
  crop: ["M7 2v15h15M2 7h15v15"],
  eye: [
    "M2 12c3-5.5 6.5-7 10-7s7 1.5 10 7c-3 5.5-6.5 7-10 7s-7-1.5-10-7z",
    "M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  ],
  gear: [
    "M19.23 9.65L21.77 9.86L21.77 14.14L19.23 14.35L18.77 15.45L20.42 17.39L17.39 20.42L15.45 18.77L14.35 19.23L14.14 21.77L9.86 21.77L9.65 19.23L8.55 18.77L6.61 20.42L3.58 17.39L5.23 15.45L4.77 14.35L2.23 14.14L2.23 9.86L4.77 9.65L5.23 8.55L3.58 6.61L6.61 3.58L8.55 5.23L9.65 4.77L9.86 2.23L14.14 2.23L14.35 4.77L15.45 5.23L17.39 3.58L20.42 6.61L18.77 8.55z",
    "M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  ],
  globe: [
    "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
    "M3 12h18",
    "M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-5.5-3.5-9s1-6.5 3.5-9z",
  ],
  layers: ["M12 3l9 5-9 5-9-5z", "M3 12l9 5 9-5", "M3 16l9 5 9-5"],
  list: ["M8 6h13M8 12h13M8 18h13", "f:M3 5h2v2H3zM3 11h2v2H3zM3 17h2v2H3z"],
  message: ["M3.5 4.5h17v12h-9l-5 4v-4h-3z"],
  pause: ["M6 5h4v14H6zM14 5h4v14h-4z"],
  phone: ["M6.5 2.5h11v19h-11z", "M10.5 18.5h3"],
  play: ["M7 4l12 8-12 8z"],
  redo: ["M15 5l5 5-5 5", "M20 10H9.5a5.5 5.5 0 0 0 0 11H13"],
  restart: ["M4 4v5.5h5.5", "M4.5 9.5A8 8 0 1 1 4 14"],
  "arrow-down": ["M12 4v15.5", "M5.5 13L12 19.5l6.5-6.5"],
  attach: [
    "M16.5 7v9a4.5 4.5 0 0 1-9 0V6.5a3 3 0 0 1 6 0V16a1.5 1.5 0 0 1-3 0V8",
  ],
  check: ["M4 12.5l5 5L20 6.5"],
  chevron: ["M6 9l6 6 6-6"],
  close: ["M5 5l14 14M19 5L5 19"],
  copy: ["M8 8h12v12H8z", "M16 8V4H4v12h4"],
  expand: ["M14 3h7v7", "M21 3l-7.5 7.5", "M10 21H3v-7", "M3 21l7.5-7.5"],
  file: ["M5 2.5h9.5L19 7v14.5H5z", "M14 2.5V7.5h5"],
  "file-edit": [
    "M11 21.5H5v-19h9.5L19 7v3.5",
    "M14 2.5V7.5h5",
    "M13.5 21.5V19l6-6 2.5 2.5-6 6z",
  ],
  fit: ["M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5", "M8.5 8.5h7v7h-7z"],
  folder: ["M2.5 4.5h7l2 2.5h10v12.5h-19z", "M2.5 10h19"],
  grid: ["M3 3h18v18H3z", "M9 3v18M15 3v18M3 9h18M3 15h18"],
  image: [
    "M3 4.5h18v15H3z",
    "M3 16l5-5 4.5 4.5 3-3L21 18",
    "f:M14.5 7.5H17V10h-2.5z",
  ],
  "link-out": ["M14 3.5h6.5V10", "M20.5 3.5l-9 9", "M18 14v6.5H3.5V6H10"],
  measure: ["M3 8v8M21 8v8M3 12h18", "M7 10.5v3M11 10.5v3M15 10.5v3M19 10.5v3"],
  model: [
    "M12 2.5l8.5 4.75v9.5L12 21.5l-8.5-4.75v-9.5z",
    "M3.5 7.25L12 12l8.5-4.75M12 12v9.5",
  ],
  monitor: ["M3 4.5h18v12H3z", "M8 20.5h8M12 16.5v4"],
  moon: ["M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"],
  more: ["f:M4 11h2.5v2.5H4zM10.75 11h2.5v2.5h-2.5zM17.5 11H20v2.5h-2.5z"],
  search: [
    "M17 10.5a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0z",
    "M15.5 15.5L21 21",
  ],
  send: ["M12 20V4.5", "M5.5 11L12 4.5l6.5 6.5"],
  "sidebar-left": ["M3 4.5h18v15H3z", "M9 4.5v15"],
  "sidebar-right": ["M3 4.5h18v15H3z", "M15 4.5v15"],
  sliders: ["M3 7h4M11 7h10M3 17h10M17 17h4", "M7 5h4v4H7zM13 15h4v4h-4z"],
  stop: ["M6 6h12v12H6z"],
  sun: [
    "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0z",
    "M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8",
  ],
  thought: [
    "M12 3a6 6 0 0 0-3.5 10.9V16.5h7v-2.6A6 6 0 0 0 12 3z",
    "M9.5 19.5h5M10.5 22h3",
  ],
  terminal: ["M3 4.5h18v15H3z", "M7 9.5l3 2.5-3 2.5", "M12.5 15H17"],
  warning: ["M12 3l10 18H2z", "M12 10v5", "f:M11 17h2v2h-2z"],
  wireframe: [
    "M12 2.5l8.5 4.75v9.5L12 21.5l-8.5-4.75v-9.5z",
    "M3.5 7.25L12 12l8.5-4.75M12 12v9.5",
    "M3.5 16.75L12 12M20.5 16.75L12 12M12 2.5V12",
  ],
} satisfies Record<string, string[]>;

export type IconName = keyof typeof PATHS;

/**
 * One of the app's icons in the current text color: 16 in dense rows, 20 in toolbars and buttons. An icon that
 * stands alone, with no text beside it to name it, takes a `label`.
 */
export function Icon({
  name,
  size = 16,
  label,
  className,
}: {
  name: IconName;
  size?: 16 | 20 | 24;
  label?: string;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="square"
      strokeLinejoin="miter"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn("block shrink-0", className)}
    >
      {PATHS[name].map((path) =>
        path.startsWith("f:") ? (
          <path
            key={path}
            d={path.slice(2)}
            fill="currentColor"
            stroke="none"
          />
        ) : (
          <path key={path} d={path} />
        ),
      )}
    </svg>
  );
}
