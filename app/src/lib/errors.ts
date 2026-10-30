/** A failure from the server, with the code the library named it by, when it named one. */
export class AppError extends Error {
  readonly code: string | null;

  constructor(message: string, code: string | null = null) {
    super(message);
    this.code = code;
  }
}

// A resource read fails as a protocol error, which carries the library's message but not its code.
const MESSAGE_CODES: [RegExp, string][] = [
  [/bytes, more than the \d+ read at once/, "evidence-too-large"],
  [
    /not a path inside the check's evidence folder|links in evidence are never followed|not a file in the check's evidence folder/,
    "not-evidence",
  ],
  [/No check '[^']*' in /, "check-not-found"],
  [/is not the checks directory of a project/, "unknown-checks-directory"],
  [/is not a list of projects/, "bad-registry"],
];

/** The library's code for a failure known only by its message. */
export function codeFromMessage(message: string): string | null {
  return MESSAGE_CODES.find(([pattern]) => pattern.test(message))?.[1] ?? null;
}

/**
 * The library's message names commands and arguments for an agent, so each failure it names is worded here for the
 * person. One without a wording here says so plainly, and its message stays behind Details.
 */
function worded(code: string | null): string | null {
  switch (code) {
    case "check-not-found":
      return "This check is not in its project's checks folder anymore. It may have been moved or deleted.";
    case "unknown-checks-directory":
      return "This check's project is not one Reality Check knows on this machine anymore.";
    case "not-evidence":
      return "That file is not in this check's evidence folder.";
    case "evidence-too-large":
      return "That file is too large to show here. Open it from the check's folder.";
    case "bad-registry":
      return "The list of projects Reality Check keeps on this machine could not be read.";
    case "bad-events":
      return "This check's activity log has a line that could not be read.";
    case "event-not-found":
      return "This check's activity changed while it was being read.";
    case "cannot-open-folder":
      return "This machine could not open the folder. Copy its path instead.";
    default:
      return null;
  }
}

/** What went wrong, for the person, and the server's own message for Details when there is one. */
export function describe(cause: unknown): {
  message: string;
  detail: string | null;
} {
  if (cause instanceof AppError) {
    return {
      message: worded(cause.code) ?? "Reality Check could not do that.",
      detail: cause.message,
    };
  }
  const detail = cause instanceof Error ? cause.message : String(cause);
  return {
    message:
      "Reality Check did not answer. Check that what served this app is still running.",
    detail,
  };
}
