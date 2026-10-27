import { cn } from "@/lib/utils";

const SIZES = { 8: "size-2", 12: "size-3", 24: "size-6", 48: "size-12" };

/**
 * The brand square building itself in four layers, wherever something is working: 8 in rows, 12 in the live strip,
 * larger in empty states. It holds still under reduced motion.
 */
export function LoadingMark({
  size = 8,
  className,
}: {
  size?: keyof typeof SIZES;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "relative inline-block shrink-0 overflow-hidden bg-accent/28 after:absolute after:inset-0 after:origin-bottom after:animate-build after:bg-accent",
        SIZES[size],
        className,
      )}
    />
  );
}
