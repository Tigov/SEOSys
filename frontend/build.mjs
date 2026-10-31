// Bundles the portal into backend/seo_platform/static, which the API serves at http://localhost:8000
// Usage: node build.mjs            (one-off production build)
//        node build.mjs --watch    (rebuild on save while developing)
import * as esbuild from "esbuild";
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outdir = join(here, "..", "backend", "seo_platform", "static");
const watch = process.argv.includes("--watch");

mkdirSync(outdir, { recursive: true });
copyFileSync(join(here, "src", "index.html"), join(outdir, "index.html"));

const options = {
  entryPoints: [join(here, "src", "main.tsx")],
  bundle: true,
  outfile: join(outdir, "app.js"),
  format: "esm",
  jsx: "automatic",
  target: ["es2022"],
  minify: !watch,
  sourcemap: watch,
  loader: { ".css": "css" },
  nodePaths: process.env.NODE_PATH ? process.env.NODE_PATH.split(process.platform === "win32" ? ";" : ":") : [],
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production") },
  logLevel: "info",
};

if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
  console.log("Watching for changes. Reload http://localhost:8000 after each rebuild.");
} else {
  await esbuild.build(options);
}
