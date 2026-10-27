import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md border border-transparent text-label whitespace-nowrap text-ink transition-[background-color,border-color,color,filter] select-none disabled:pointer-events-none data-disabled:pointer-events-none",
  {
    variants: {
      variant: {
        primary:
          "bg-accent text-on-accent hover:brightness-93 disabled:border-line disabled:bg-field disabled:text-ink-faint",
        secondary:
          "border-line-control bg-panel hover:bg-hover aria-expanded:bg-hover disabled:border-line disabled:bg-field disabled:text-ink-faint",
        ghost:
          "hover:bg-hover aria-expanded:bg-hover aria-pressed:border-line-control aria-pressed:bg-field aria-pressed:text-accent-ink disabled:text-ink-faint",
        danger:
          "bg-danger text-on-danger hover:brightness-93 disabled:border-line disabled:bg-field disabled:text-ink-faint",
      },
      size: {
        sm: "h-6 px-2",
        md: "h-7 px-3",
        lg: "h-9 px-4 text-body font-medium",
      },
      icon: { true: "px-0" },
    },
    compoundVariants: [
      { size: "sm", icon: true, className: "w-6" },
      { size: "md", icon: true, className: "w-7" },
      { size: "lg", icon: true, className: "w-9" },
    ],
    defaultVariants: { variant: "ghost", size: "md", icon: false },
  },
);

/** A button: primary for the one main action in a view, secondary beside it, ghost in toolbars and rows. */
function Button({
  className,
  variant,
  size,
  icon,
  type = "button",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      type={type}
      className={cn(buttonVariants({ variant, size, icon }), className)}
      {...props}
    />
  );
}

export { Button, buttonVariants };
