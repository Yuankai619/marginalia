import { readFileSync } from "node:fs";
import ts from "typescript";

const cache = new Map();

async function url(name) {
  if (cache.has(name)) return cache.get(name);
  const source = readFileSync(new URL(`../src/lib/${name}.ts`, import.meta.url), "utf8");
  let { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  // data: modules cannot resolve relative specifiers, so sibling modules are inlined the same way.
  for (const [, dependency] of outputText.matchAll(/from "\.\/([\w-]+)"/g))
    outputText = outputText.replace(`from "./${dependency}"`, `from "${await url(dependency)}"`);
  const result = `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`;
  cache.set(name, result);
  return result;
}

/** Imports a module from src/lib; type-only imports are erased and sibling imports are inlined. */
export async function load(name) {
  return import(await url(name));
}
