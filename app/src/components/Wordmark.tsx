import { cn } from "@/lib/utils";

/** The app's name in the brand's type, with the pink square where a period would be. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-baseline text-[14px]/4 font-semibold tracking-[-0.015em] whitespace-nowrap text-ink",
        className,
      )}
    >
      Reality Check
      <span
        aria-hidden
        className="ml-[0.12em] inline-block size-[0.3em] shrink-0 bg-accent"
      />
    </span>
  );
}

/** The compact mark: a drawn check on an ink tile, with the square. */
export function AppMark({
  size = 20,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      role="img"
      aria-label="Reality Check"
      className={cn("block shrink-0", className)}
    >
      <rect width="64" height="64" rx="14" fill="#12161c" />
      <path
        d="M14 33l10 10 22-23"
        fill="none"
        stroke="#eef2f6"
        strokeWidth="4.5"
        strokeLinecap="square"
      />
      <rect x="44" y="44" width="11" height="11" fill="#f2a7c3" />
    </svg>
  );
}
