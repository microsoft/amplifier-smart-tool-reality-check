import { Details } from "@/components/EvidenceContent";
import { Notice } from "@/components/ui/notice";
import { describe } from "@/lib/errors";

/** A failure worded for the person, with the server's own message behind Details. */
export function ErrorNotice({
  error,
  title,
  className,
}: {
  error: unknown;
  title: string;
  className?: string;
}) {
  const { message, detail } = describe(error);
  return (
    <Notice title={title} className={className}>
      {message}
      {detail && <Details text={detail} />}
    </Notice>
  );
}
