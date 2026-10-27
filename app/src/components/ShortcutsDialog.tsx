import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";

const SHORTCUTS: [string[], string][] = [
  [["["], "Show or hide checks"],
  [["]"], "Show or hide activity"],
  [["J", "K"], "Next or previous check"],
  [["E"], "Evidence"],
  [["Esc"], "Back, or close"],
  [["Backspace"], "Back"],
  [["Left", "Right"], "The file before or after, in the viewer"],
  [["Z"], "Fit or 100%, in the viewer"],
  [["?"], "This list"],
];

/** Every key the app answers to. */
export function ShortcutsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Keyboard shortcuts" className="sm:max-w-100">
        <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 px-5 py-4">
          {SHORTCUTS.map(([keys, action]) => (
            <div key={action} className="contents">
              <dt className="flex gap-1">
                {keys.map((key) => (
                  <Kbd key={key}>{key}</Kbd>
                ))}
              </dt>
              <dd>{action}</dd>
            </div>
          ))}
        </dl>
        <p className="px-5 pb-5 text-caption text-ink-muted">
          Single keys act only when you are not typing in a field.
        </p>
      </DialogContent>
    </Dialog>
  );
}
