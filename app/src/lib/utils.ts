import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Without these, `text-body` reads as a text color and `cn` drops it beside `text-ink`.
const twMerge = extendTailwindMerge({
  extend: {
    theme: { text: ["display", "title", "body", "label", "caption"] },
    classGroups: { "font-size": ["mono-value", "mono-annotation"] },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Put `text` on the clipboard; true when it got there. A host may not let a sandboxed view write it directly. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.cssText = "position: fixed; opacity: 0;";
    document.body.append(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    return copied;
  }
}
