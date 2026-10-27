import { useEffect, useRef, useState, type RefObject } from "react";

import { readEvidence, type CheckReference } from "@/lib/api";
import type { Evidence } from "@/lib/evidence";
import { keyOf } from "@/lib/store";

const MAX_PARALLEL = 4;
// Whole files kept for the viewer, oldest dropped first: a check's screenshots run to hundreds of megabytes.
const MAX_KEPT_BYTES = 96 * 1024 * 1024;
const MAX_KEPT_THUMBNAILS = 600;
const THUMBNAIL_WIDTH = 480;

// A data: URL, since an MCP App host must allow data: images and media in the view's frame but need not allow blob:.
type File = { blob: Blob; url: string };

/** A cache that drops what was used longest ago once it holds more than `limit`, by `size` of each entry. */
class Lru<T> {
  private readonly entries = new Map<
    string,
    { value: Promise<T>; size: number }
  >();
  private total = 0;
  private readonly limit: number;

  constructor(limit: number) {
    this.limit = limit;
  }

  get(key: string): Promise<T> | undefined {
    const entry = this.entries.get(key);
    if (entry) {
      this.entries.delete(key);
      this.entries.set(key, entry);
    }
    return entry?.value;
  }

  set(key: string, value: Promise<T>) {
    this.entries.set(key, { value, size: 0 });
    value.catch(() => this.entries.delete(key));
  }

  /** Records how large `key` turned out to be, and drops the oldest entries past the limit. */
  sized(key: string, size: number) {
    const entry = this.entries.get(key);
    if (!entry) {
      return;
    }
    this.total += size - entry.size;
    entry.size = size;
    for (const [oldest, { size: bytes }] of this.entries) {
      if (this.total <= this.limit || oldest === key) {
        break;
      }
      this.entries.delete(oldest);
      this.total -= bytes;
    }
  }
}

const files = new Lru<File>(MAX_KEPT_BYTES);
const thumbnails = new Lru<string>(MAX_KEPT_THUMBNAILS);
let active = 0;
const waiting: (() => void)[] = [];

async function slot(): Promise<() => void> {
  if (active >= MAX_PARALLEL) {
    await new Promise<void>((resolve) => waiting.push(resolve));
  }
  active += 1;
  return () => {
    active -= 1;
    waiting.shift()?.();
  };
}

function bytesOf(base64: string): Uint8Array<ArrayBuffer> {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function fileKey(ref: CheckReference, item: Evidence): string {
  return `${keyOf(ref)}\n${item.path}\n${item.size}\n${item.modified_at}`;
}

/** An evidence file read through the host, at most a few at once, in the type the folder listing gave. */
async function read(ref: CheckReference, item: Evidence): Promise<File> {
  const release = await slot();
  try {
    const data = await readEvidence(ref, item.path);
    // The listing's type, so a page saved as HTML still shows as text.
    const type = item.media_type || data.mimeType;
    return {
      blob: new Blob([bytesOf(data.base64)], { type }),
      url: `data:${type};base64,${data.base64}`,
    };
  } finally {
    release();
  }
}

/** One evidence file, read once and kept while there is room, with a URL to show it by. */
export function loadEvidence(
  ref: CheckReference,
  item: Evidence,
): Promise<File> {
  const key = fileKey(ref, item);
  let file = files.get(key);
  if (!file) {
    file = read(ref, item);
    files.set(key, file);
    void file.then(
      (loaded) => files.sized(key, loaded.blob.size + loaded.url.length),
      () => {},
    );
  }
  return file;
}

/**
 * A small picture of the top of a screenshot. A full screenshot decodes to tens of megabytes, so a gallery of them as
 * full images is what makes a page with hundreds of them slow.
 */
async function shrink(blob: Blob): Promise<string> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(blob, {
      resizeWidth: THUMBNAIL_WIDTH,
      resizeQuality: "medium",
    });
  } catch {
    bitmap = await createImageBitmap(blob);
  }
  const width = Math.min(THUMBNAIL_WIDTH, bitmap.width);
  const scale = width / bitmap.width;
  const height = Math.min(Math.round(bitmap.height * scale), width);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  canvas
    .getContext("2d")
    ?.drawImage(bitmap, 0, 0, width, Math.round(bitmap.height * scale));
  bitmap.close();
  return canvas.toDataURL("image/webp", 0.82);
}

/** A thumbnail's URL; the whole file is read for it but not kept, unless the viewer already holds it. */
function loadThumbnail(ref: CheckReference, item: Evidence): Promise<string> {
  const key = fileKey(ref, item);
  let url = thumbnails.get(key);
  if (!url) {
    const held = files.get(key);
    url = (held ?? read(ref, item)).then((file) => shrink(file.blob));
    thumbnails.set(key, url);
    void url.then(
      () => thumbnails.sized(key, 1),
      () => {},
    );
  }
  return url;
}

type Read<T> = { value: T | null; error: unknown };

function useRead<T>(
  ref: CheckReference,
  item: Evidence | undefined,
  enabled: boolean,
  load: (ref: CheckReference, item: Evidence) => Promise<T>,
): Read<T> & { loading: boolean } {
  const key = item ? fileKey(ref, item) : "";
  const [state, setState] = useState<Read<T> & { key: string }>({
    key: "",
    value: null,
    error: null,
  });
  const latest = useRef(load);
  useEffect(() => {
    latest.current = load;
  });
  useEffect(() => {
    if (!item || !enabled) {
      return;
    }
    let live = true;
    latest.current(ref, item).then(
      (value) => live && setState({ key, value, error: null }),
      (error: unknown) => live && setState({ key, value: null, error }),
    );
    return () => {
      live = false;
    };
    // The key names the file and its version, so the file is read again only when it changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);
  const current = state.key === key ? state : { value: null, error: null };
  return {
    ...current,
    loading:
      Boolean(item) && enabled && current.value === null && !current.error,
  };
}

/** A URL to show an evidence file by, once it is read. */
export function useEvidenceUrl(
  ref: CheckReference,
  item: Evidence | undefined,
  enabled = true,
) {
  return useRead(
    ref,
    item,
    enabled,
    async (checkRef, file) => (await loadEvidence(checkRef, file)).url,
  );
}

/** A URL to a small picture of a screenshot, once it is read. */
export function useThumbnailUrl(
  ref: CheckReference,
  item: Evidence | undefined,
  enabled = true,
) {
  return useRead(ref, item, enabled, loadThumbnail);
}

/** An evidence file's text, once it is read. */
export function useEvidenceText(
  ref: CheckReference,
  item: Evidence | undefined,
) {
  return useRead(ref, item, true, async (checkRef, file) =>
    (await loadEvidence(checkRef, file)).blob.text(),
  );
}

/** Whether `element` has come near the screen, so a thumbnail reads its file only once it could be seen. */
export function useSeen(element: RefObject<HTMLElement | null>): boolean {
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const target = element.current;
    if (!target || seen) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setSeen(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [element, seen]);
  return seen;
}
