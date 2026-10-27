import { useEffect, useRef, useState, type ReactNode } from "react";

import { EvidenceContent } from "@/components/EvidenceContent";
import { EvidenceImage } from "@/components/EvidenceImage";
import { Button } from "@/components/ui/button";
import { Dimension } from "@/components/ui/dimension";
import { CropMarks } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { Kbd } from "@/components/ui/kbd";
import { Segmented } from "@/components/ui/segmented";
import { Tooltip } from "@/components/ui/tooltip";
import {
  isImage,
  KIND_ICONS,
  KIND_LABELS,
  type Evidence,
} from "@/lib/evidence";
import { bytes } from "@/lib/format";
import type { Check } from "@/lib/store";
import { offset, timeOfDay } from "@/lib/time";
import { cn, copyText } from "@/lib/utils";

export type ViewerState = { path: string; list: string[] };

type Zoom = "fit" | "actual";

const PAD = 48;

function useSize() {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const element = ref.current;
    if (!element) {
      return;
    }
    const observer = new ResizeObserver(([entry]) =>
      setSize({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      }),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, size] as const;
}

/** A screenshot on the canvas, framed with crop marks and a dimension line giving its size in pixels. */
function ImageStage({
  check,
  item,
  zoom,
}: {
  check: Check;
  item: Evidence;
  zoom: Zoom;
}) {
  const [ref, room] = useSize();
  const [natural, setNatural] = useState<{
    path: string;
    size: [number, number];
  } | null>(null);
  const [width, height] = natural?.path === item.path ? natural.size : [0, 0];
  const pad = room.width < 640 ? 14 : PAD;
  const fit =
    width && room.width
      ? Math.min(
          1,
          (room.width - pad * 2) / width,
          (room.height - pad * 2 - 40) / height,
        )
      : 1;
  const scale = zoom === "fit" ? Math.max(0.05, fit) : 1;
  return (
    <div ref={ref} className="flex size-full overflow-auto bg-canvas">
      <figure className="m-auto flex shrink-0 flex-col p-6 max-sm:p-0.5">
        <div className="px-3 pb-1.5">
          <Dimension tone="control">
            {width ? `${width} x ${height} px` : "Reading the file"}
          </Dimension>
        </div>
        <div className="relative p-3">
          <CropMarks />
          <EvidenceImage
            key={item.path}
            checkRef={check.ref}
            item={item}
            alt={item.name}
            onLoad={(image) =>
              setNatural({
                path: item.path,
                size: [image.naturalWidth, image.naturalHeight],
              })
            }
            style={
              width
                ? { width: width * scale, height: height * scale }
                : { width: 240, height: 160 }
            }
            className="block max-w-none border border-line bg-panel"
          />
        </div>
        <figcaption className="flex justify-between gap-4 px-3 mono-annotation text-ink-muted">
          <span className="min-w-0 truncate">{item.name}</span>
          <span>{Math.round(scale * 100)}%</span>
        </figcaption>
      </figure>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-caption text-ink-muted">{label}</dt>
      <dd className="min-w-0 mono-value break-all">{children}</dd>
    </div>
  );
}

/** One evidence file at full size, with what it is and whether the report cites it; arrows step through the list. */
export function EvidenceViewer({
  check,
  state,
  onChange,
  onClose,
  onShowInActivity,
  toast,
}: {
  check: Check;
  state: ViewerState;
  onChange: (state: ViewerState) => void;
  onClose: () => void;
  onShowInActivity: (path: string) => void;
  toast: (text: string) => void;
}) {
  const [zoom, setZoom] = useState<Zoom>("fit");
  // Focus starts on the stage, not the zoom switch, so the arrow keys step through files.
  const stage = useRef<HTMLDivElement>(null);
  const files = new Map(check.evidence.map((item) => [item.path, item]));
  const list = (
    state.list.length ? state.list : check.evidence.map((item) => item.path)
  ).filter((path) => files.has(path));
  const index = list.indexOf(state.path);
  const item = files.get(state.path);
  const go = (step: number) => {
    const next = list[index + step];
    if (next) {
      onChange({ ...state, path: next });
    }
  };

  useEffect(() => {
    stage.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement ||
        (event.target instanceof HTMLElement &&
          event.target.closest("[role=radiogroup]"))
      ) {
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        go(-1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        go(1);
      } else if (event.key.toLowerCase() === "z") {
        setZoom((current) => (current === "fit" ? "actual" : "fit"));
      }
    };
    // Capture, since a dialog's focus handling stops some keys before they bubble to the window.
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  const absolute = check.directory ? `${check.directory}/${state.path}` : null;

  return (
    <div className="absolute inset-0 z-20 flex">
      <button
        type="button"
        aria-label="Close the viewer"
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 animate-[fade_120ms_ease-out] bg-scrim"
      />
      <section
        role="region"
        aria-label="Evidence viewer"
        className="relative m-3 flex min-w-0 flex-1 animate-[appear_140ms_ease-out] flex-col overflow-hidden rounded-lg bg-raised text-ink shadow-popover max-sm:m-1.5"
      >
        {!item && (
          <div className="m-auto flex flex-col items-center gap-3 p-6 text-center text-ink-muted">
            <p>
              <span className="mono-value text-ink">{state.path}</span> is not
              in this check&apos;s evidence folder.
            </p>
            <Button variant="secondary" size="sm" onClick={onClose}>
              Back
            </Button>
          </div>
        )}
        {item && (
          <>
            <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line pr-2 pl-4">
              <Icon
                name={KIND_ICONS[item.kind]}
                className="shrink-0 text-ink-muted max-sm:hidden"
              />
              <div className="flex min-w-0 flex-col">
                <h2 className="truncate mono-value">{item.name}</h2>
                <p className="truncate mono-annotation text-ink-muted">
                  {item.ext || "file"}, {bytes(item.size)}
                </p>
              </div>
              <span className="flex-1" />
              {isImage(item) && (
                <Segmented
                  label="Zoom"
                  size="sm"
                  value={zoom}
                  onChange={setZoom}
                  options={[
                    { value: "fit", label: "Fit", icon: "fit" },
                    { value: "actual", label: "100%" },
                  ]}
                  className="max-sm:hidden"
                />
              )}
              <span
                aria-hidden
                className="mx-1 h-5 w-px bg-line max-sm:hidden"
              />
              <span className="mono-annotation text-ink-muted tabular-nums max-sm:hidden">
                {index + 1} / {list.length}
              </span>
              <Tooltip content="Previous" keys="Left">
                <Button
                  size="sm"
                  icon
                  aria-label="Previous"
                  disabled={index <= 0}
                  onClick={() => go(-1)}
                >
                  <Icon name="arrow-left" />
                </Button>
              </Tooltip>
              <Tooltip content="Next" keys="Right">
                <Button
                  size="sm"
                  icon
                  aria-label="Next"
                  disabled={index >= list.length - 1}
                  onClick={() => go(1)}
                >
                  <Icon name="arrow-right" />
                </Button>
              </Tooltip>
              <Tooltip content="Back" keys="Esc">
                <Button size="sm" icon aria-label="Close" onClick={onClose}>
                  <Icon name="close" />
                </Button>
              </Tooltip>
            </header>
            <div className="flex min-h-0 flex-1 max-md:flex-col">
              <div
                ref={stage}
                tabIndex={-1}
                className="relative min-h-0 min-w-0 flex-1 overflow-hidden outline-none"
              >
                {isImage(item) ? (
                  <ImageStage check={check} item={item} zoom={zoom} />
                ) : (
                  <div className="size-full overflow-auto bg-panel">
                    <EvidenceContent
                      key={item.path}
                      checkRef={check.ref}
                      item={item}
                      onEvidence={(path) =>
                        files.has(path) && onChange({ path, list })
                      }
                    />
                  </div>
                )}
              </div>
              <aside className="flex w-[28%] max-w-80 min-w-60 shrink-0 flex-col gap-5 overflow-y-auto border-l border-line bg-panel p-4 max-md:max-h-[40%] max-md:w-full max-md:max-w-none max-md:min-w-0 max-md:border-t max-md:border-l-0">
                <span className="flex flex-wrap gap-1.5">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => onShowInActivity(item.path)}
                  >
                    <Icon name="message" />
                    Show in activity
                  </Button>
                  {absolute && (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        void copyText(absolute).then((copied) =>
                          toast(
                            copied ? "Path copied" : "Could not copy the path",
                          ),
                        )
                      }
                    >
                      <Icon name="copy" />
                      Copy path
                    </Button>
                  )}
                </span>
                <dl className="flex flex-col gap-3">
                  <Row label="Path">{item.path}</Row>
                  <Row label="Kind">{KIND_LABELS[item.kind]}</Row>
                  <Row label="Size">{bytes(item.size)}</Row>
                  <Row label="Saved">
                    {offset(check.summary.started_at, item.modified_at)} into
                    the check, {timeOfDay(item.modified_at)}
                  </Row>
                  <Row label="In the report">
                    <span className={cn(!item.referenced && "text-ink-muted")}>
                      {check.report === null
                        ? "No report yet"
                        : item.referenced
                          ? "Cited"
                          : "Not cited"}
                    </span>
                  </Row>
                </dl>
                <p className="mt-auto flex flex-wrap items-center gap-1.5 text-caption text-ink-muted max-md:hidden">
                  <Kbd>Left</Kbd>
                  <Kbd>Right</Kbd> step through
                  {isImage(item) && (
                    <>
                      <Kbd>Z</Kbd> zoom
                    </>
                  )}
                  <Kbd>Esc</Kbd> back
                </p>
              </aside>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
