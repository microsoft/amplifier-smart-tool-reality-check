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
  // `--mode demo` and `--mode demo-view` build the example on the website: a static page that answers one recorded check,
  // and a view of that check's report and activity it hosts. The default build is the app's own browser host page and
  // its sandbox proxy.
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
    : mode === "demo"
      ? {
          root: path.resolve(import.meta.dirname, "demo"),
          base: "./",
          publicDir: "fixture",
          plugins: [viteSingleFile()],
          build: {
            outDir: "../../site/demo",
            emptyOutDir: true,
          },
        }
      : mode === "demo-view"
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
              // The input's own path, demo/view.html, puts it beside the page `--mode demo` builds.
              outDir: "../site",
              emptyOutDir: false,
              rolldownOptions: { input: "demo/view.html" },
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
