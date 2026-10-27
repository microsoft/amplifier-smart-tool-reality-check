/** What the server filled into the view's meta tag `name`; nothing when it was served without one. */
function served(name: string): string | null {
  const content = document
    .querySelector<HTMLMetaElement>(`meta[name="${name}"]`)
    ?.content.trim();
  return content && !content.startsWith("{{") ? content : null;
}

/** The tool's version. */
export const VERSION = served("reality-check-version");

/** The tool's repository, where its docs are. */
export const REPOSITORY = served("reality-check-repository");
