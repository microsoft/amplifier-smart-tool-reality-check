import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import { Tooltip } from "@/components/ui/tooltip";
import { openCheckFolder } from "@/lib/api";
import { describe } from "@/lib/errors";
import { useStore, type Check } from "@/lib/store";
import { useUi } from "@/lib/ui";
import { copyText } from "@/lib/utils";

/** What can be done with the check shown: copy its id or folder, or open the folder on the server's machine. */
export function CheckMenu({ check }: { check: Check }) {
  const { toast } = useUi();
  const { canOpenFolders } = useStore();
  const copy = (text: string, what: string) =>
    void copyText(text).then((copied) =>
      toast(
        copied ? `${what} copied` : `Could not copy the ${what.toLowerCase()}`,
      ),
    );
  const openFolder = async () => {
    try {
      await openCheckFolder(check.ref);
      toast("Opened in your file manager");
    } catch (cause) {
      toast(describe(cause).message);
    }
  };
  return (
    <Menu>
      <Tooltip content="More">
        <MenuTrigger
          render={
            <Button size="sm" icon aria-label="More" className="shrink-0" />
          }
        >
          <Icon name="more" />
        </MenuTrigger>
      </Tooltip>
      <MenuContent align="end">
        {canOpenFolders && (
          <>
            <MenuItem onClick={() => void openFolder()}>
              <Icon name="folder" className="text-ink-muted" />
              Open folder
            </MenuItem>
            <MenuSeparator />
          </>
        )}
        <MenuItem onClick={() => copy(check.id, "Check id")}>
          <Icon name="copy" className="text-ink-muted" />
          Copy check id
        </MenuItem>
        {check.directory && (
          <MenuItem
            onClick={() => check.directory && copy(check.directory, "Path")}
          >
            <Icon name="copy" className="text-ink-muted" />
            Copy folder path
          </MenuItem>
        )}
      </MenuContent>
    </Menu>
  );
}
