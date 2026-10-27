import { EvidenceImage } from "@/components/EvidenceImage";
import { Icon } from "@/components/ui/icon";
import type { CheckReference } from "@/lib/api";
import {
  isImage,
  KIND_ICONS,
  KIND_LABELS,
  type Evidence,
} from "@/lib/evidence";
import { bytes, middle } from "@/lib/format";
import { cn } from "@/lib/utils";

/** One piece of evidence as a small tile: a screenshot's picture, or a file's kind and name. */
export function EvidenceThumb({
  checkRef,
  item,
  onOpen,
  className,
  caption = true,
}: {
  checkRef: CheckReference;
  item: Evidence;
  onOpen: () => void;
  className?: string;
  caption?: boolean;
}) {
  const image = isImage(item);
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        onOpen();
      }}
      title={item.name}
      className={cn(
        "group/thumb flex w-33 shrink-0 flex-col gap-1 text-left",
        className,
      )}
    >
      <span className="relative block aspect-3/2 w-full overflow-hidden rounded-sm border border-line bg-field transition-colors group-hover/thumb:border-line-control">
        {image ? (
          <EvidenceImage
            thumbnail
            checkRef={checkRef}
            item={item}
            className="size-full object-cover object-top"
          />
        ) : (
          <span className="flex size-full flex-col gap-1.5 bg-panel p-2 text-ink-muted">
            <span className="flex items-center gap-1.5">
              <Icon name={KIND_ICONS[item.kind]} />
              <span className="mono-annotation uppercase">
                {item.ext || "file"}
              </span>
            </span>
            <span className="line-clamp-3 mono-annotation break-all text-ink">
              {item.name}
            </span>
          </span>
        )}
        <span className="absolute inset-0 hidden place-items-center bg-panel/60 text-ink group-hover/thumb:grid">
          <Icon name="expand" />
        </span>
      </span>
      {caption && (
        <span className="truncate mono-annotation text-ink-muted group-hover/thumb:text-ink">
          {image
            ? middle(item.name)
            : `${KIND_LABELS[item.kind]}, ${bytes(item.size)}`}
        </span>
      )}
    </button>
  );
}
