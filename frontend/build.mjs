// Bundles the portal into backend/seo_platform/static, which the API serves at http://localhost:8000
// Usage: node build.mjs            (one-off production build)
//        node build.mjs --watch    (rebuild on save while developing)
//
// Script and style files get a hash of their content in the name (assets/app-3F2A1B.js), and index.html is
// rewritten to point at them. Browsers can cache them forever, and a new build is picked up on the next load.
import * as esbuild from "esbuild";
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outdir = join(here, "..", "backend", "seo_platform", "static");
const assets = join(outdir, "assets");
const watch = process.argv.includes("--watch");

mkdirSync(assets, { recursive: true });
for (const old of ["app.js", "app.css"]) rmSync(join(outdir, old), { force: true });  // names from before hashing

function writeIndex(outputs) {
  const files = Object.keys(outputs).map((f) => basename(f));
  const js = files.find((f) => f.endsWith(".js"));
  const css = files.find((f) => f.endsWith(".css"));
  for (const f of readdirSync(assets)) if (f !== js && f !== css && !f.endsWith(".map")) rmSync(join(assets, f));
  const html = readFileSync(join(here, "src", "index.html"), "utf8")
    .replace('href="/app.css"', `href="/assets/${css}"`)
    .replace('src="/app.js"', `src="/assets/${js}"`);
  writeFileSync(join(outdir, "index.html"), html);
}

const options = {
  entryPoints: { app: join(here, "src", "main.tsx") },
  bundle: true,
  outdir: assets,
  entryNames: "[name]-[hash]",
  metafile: true,
  format: "esm",
  jsx: "automatic",
  target: ["es2022"],
  minify: !watch,
  sourcemap: watch,
  loader: { ".css": "css" },
  nodePaths: process.env.NODE_PATH ? process.env.NODE_PATH.split(process.platform === "win32" ? ";" : ":") : [],
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production") },
  logLevel: "info",
  plugins: [{ name: "index-html", setup(build) { build.onEnd((r) => { if (r.metafile) writeIndex(r.metafile.outputs); }); } }],
};

if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
  console.log("Watching for changes. Reload http://localhost:8000 after each rebuild.");
} else {
  await esbuild.build(options);
}
