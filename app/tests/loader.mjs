import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import ts from "typescript";

export async function resolve(specifier, context, nextResolve) {
  const url = specifier.startsWith("@/")
    ? new URL(`../src/${specifier.slice(2)}`, import.meta.url)
    : specifier.startsWith(".")
      ? new URL(specifier, context.parentURL)
      : null;
  if (url) {
    for (const extension of ["", ".ts", ".tsx"]) {
      const candidate = new URL(`${url.href}${extension}`);
      if (existsSync(fileURLToPath(candidate))) {
        return nextResolve(candidate.href, context);
      }
    }
  }
  return nextResolve(specifier, context);
}

export async function load(url, context, nextLoad) {
  if (!/\.(ts|tsx)$/.test(url)) {
    return nextLoad(url, context);
  }
  const source = await readFile(new URL(url), "utf8");
  return {
    format: "module",
    shortCircuit: true,
    source: ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.ESNext,
        target: ts.ScriptTarget.ESNext,
        jsx: ts.JsxEmit.ReactJSX,
      },
      fileName: fileURLToPath(url),
    }).outputText,
  };
}
