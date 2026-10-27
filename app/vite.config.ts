import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import babel from "@rolldown/plugin-babel";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

const STATIC = "../src/reality_check/capabilities/app/static";

// https://vite.dev/config/
export default defineConfig(({ mode }) =>
  // `--mode view` builds the MCP App view: one self-contained HTML file, because hosts load it as a single resource.
  // The default build is the app's own browser host page and its sandbox proxy, which render that view.
  mode === "view"
    ? {
        plugins: [
          react(),
          tailwindcss(),
          babel({ presets: [reactCompilerPreset()] }),
          viteSingleFile(),
        ],
        resolve: {
          alias: {
            "@": path.resolve(import.meta.dirname, "./src"),
          },
        },
        publicDir: false,
        build: {
          outDir: `${STATIC}/view`,
          emptyOutDir: true,
          rolldownOptions: { input: "mcp_app.html" },
        },
      }
    : {
        build: {
          outDir: `${STATIC}/host`,
          emptyOutDir: true,
          rolldownOptions: { input: ["index.html", "sandbox.html"] },
        },
      },
);
