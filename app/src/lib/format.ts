const COMPACT = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const WHOLE = new Intl.NumberFormat("en-US");

export function compact(value: number): string {
  return COMPACT.format(value);
}

export function whole(value: number): string {
  return WHOLE.format(Math.round(value));
}

export function bytes(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

/** A home-relative path where it can be: /home/me/x becomes ~/x. */
export function shortPath(path: string): string {
  return path.replace(/^\/(home|Users)\/[^/]+/, "~");
}

/** A long name shortened in the middle, keeping its start and its ending: checkout...viewport.png. */
export function middle(name: string, max = 26): string {
  if (name.length <= max) {
    return name;
  }
  // Keep the last dash-separated part whole when it fits, so "-viewport.png" stays readable.
  const dash = name.lastIndexOf("-");
  const natural = dash > 0 ? name.length - dash : 0;
  const tail =
    natural > 0 && natural <= max * 0.55
      ? natural
      : Math.ceil((max - 1) * 0.42);
  return `${name.slice(0, max - 1 - tail)}...${name.slice(-tail)}`;
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

const PROVIDERS: Record<string, string> = {
  copilot: "Copilot",
  "amplifier-agent": "Amplifier Agent",
  codex: "Codex",
  claude: "Claude",
};

/** An agent provider by the name its own product goes by. */
export function providerName(provider: string): string {
  return PROVIDERS[provider] ?? provider;
}
