import { register } from "node:module";

register("./loader.mjs", import.meta.url);

// Report rendering does not connect to a host; theme startup needs these browser APIs.
globalThis.window = {
  matchMedia: () => ({ matches: false, addEventListener() {} }),
};
globalThis.document = {
  documentElement: { dataset: {}, style: {} },
};
