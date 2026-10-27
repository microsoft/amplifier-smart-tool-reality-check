import { cn } from "@/lib/utils";

/** The 2px accent bar that runs along an edge while a check runs; it holds still under reduced motion. */
export function ProgressBar({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-x-0 top-0 h-0.5 overflow-hidden bg-accent-soft after:absolute after:inset-y-0 after:w-[32%] after:animate-slide after:bg-accent",
        className,
      )}
    />
  );
}
