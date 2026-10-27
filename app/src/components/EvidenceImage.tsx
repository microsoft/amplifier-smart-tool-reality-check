import { useRef, type CSSProperties } from "react";

import { Icon } from "@/components/ui/icon";
import type { CheckReference } from "@/lib/api";
import type { Evidence } from "@/lib/evidence";
import { useEvidenceUrl, useSeen, useThumbnailUrl } from "@/lib/files";
import { cn } from "@/lib/utils";

/** A screenshot from a check's evidence, read through the host once it comes near the screen. */
export function EvidenceImage({
  checkRef,
  item,
  thumbnail = false,
  alt = "",
  className,
  onLoad,
  style,
}: {
  checkRef: CheckReference;
  item: Evidence;
  /** A small picture of its top, for galleries, rather than the whole image. */
  thumbnail?: boolean;
  alt?: string;
  className?: string;
  onLoad?: (image: HTMLImageElement) => void;
  style?: CSSProperties;
}) {
  const holder = useRef<HTMLSpanElement>(null);
  const seen = useSeen(holder);
  const full = useEvidenceUrl(checkRef, item, seen && !thumbnail);
  const small = useThumbnailUrl(checkRef, item, seen && thumbnail);
  const { value: url, error } = thumbnail ? small : full;
  if (!url) {
    return (
      <span
        ref={holder}
        className={cn(
          "grid place-items-center bg-field text-ink-faint",
          className,
        )}
        style={style}
      >
        {error ? (
          <Icon name="warning" label="Could not read this file" />
        ) : null}
      </span>
    );
  }
  return (
    <img
      src={url}
      alt={alt}
      decoding="async"
      onLoad={(event) => onLoad?.(event.currentTarget)}
      className={className}
      style={style}
    />
  );
}
