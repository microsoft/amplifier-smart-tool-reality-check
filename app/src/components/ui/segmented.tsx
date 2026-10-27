import { Radio } from "@base-ui/react/radio";
import { RadioGroup } from "@base-ui/react/radio-group";

import { Icon, type IconName } from "@/components/ui/icon";
import { cn } from "@/lib/utils";

export type SegmentedOption<Value extends string> = {
  value: Value;
  label: string;
  icon?: IconName;
};

/** A switch between modes that change what the screen shows, one of which is always on. */
export function Segmented<Value extends string>({
  value,
  onChange,
  options,
  label,
  size = "md",
  full = false,
  className,
}: {
  value: Value;
  onChange: (value: Value) => void;
  options: SegmentedOption<Value>[];
  label: string;
  size?: "sm" | "md";
  full?: boolean;
  className?: string;
}) {
  return (
    <RadioGroup
      value={value}
      onValueChange={(next) => onChange(next as Value)}
      aria-label={label}
      className={cn(
        "shrink-0 gap-0.5 rounded-md border border-line bg-field p-0.5",
        full ? "flex" : "inline-flex",
        className,
      )}
    >
      {options.map((option) => (
        <Radio.Root
          key={option.value}
          value={option.value}
          className={cn(
            "inline-flex cursor-default items-center justify-center gap-1.5 rounded-sm border border-transparent text-label whitespace-nowrap text-ink-muted transition-colors select-none hover:text-ink data-checked:border-accent-ink data-checked:bg-accent-soft data-checked:text-ink",
            size === "sm" ? "h-4.5 px-2" : "h-5.5 px-3",
            full && "flex-1",
          )}
        >
          {option.icon && <Icon name={option.icon} />}
          {option.label}
        </Radio.Root>
      ))}
    </RadioGroup>
  );
}
