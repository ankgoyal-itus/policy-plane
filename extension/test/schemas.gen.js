#!/usr/bin/env node
// Emit recipes/schemas.json from the recipe files themselves.
//
// The plane cannot import a recipe -- recipes live in the extension, by design. So the
// contract between them is this generated file: what each recipe is called, and which
// params it requires. Python validates that every button it renders supplies them, at
// BUILD time. Before this existed, a missing param surfaced as BAD_PARAMS in the
// browser, at click time, which is the worst place to find out.
const fs = require("node:fs");
const path = require("node:path");

const dir = path.join(__dirname, "..", "recipes");
globalThis.PPRecipes = {};
for (const f of fs.readdirSync(dir).filter((f) => f.endsWith(".js"))) {
  eval(fs.readFileSync(path.join(dir, f), "utf8"));
}

const out = {};
for (const [id, r] of Object.entries(globalThis.PPRecipes)) {
  out[id] = {
    version: r.version,
    calibrated: r.calibrated !== false,
    mode: r.mode,
    required: Object.entries(r.params).filter(([, s]) => s.required)
                    .map(([k]) => k).sort(),
    optional: Object.entries(r.params).filter(([, s]) => !s.required)
                    .map(([k]) => k).sort(),
    reads: (r.read || []).map((x) => x.as).sort(),
  };
}
// Sorted by key so the checked-in file is stable and a diff means a real change.
// (JSON.stringify's second argument is a key FILTER, not a sort -- passing the ids
// there silently emitted three empty objects.)
const sorted = {};
for (const k of Object.keys(out).sort()) sorted[k] = out[k];
const text = JSON.stringify(sorted, null, 2) + "\n";
const target = path.join(dir, "schemas.json");
if (process.argv.includes("--check")) {
  const have = fs.existsSync(target) ? fs.readFileSync(target, "utf8") : "";
  if (have !== text) {
    console.error("recipes/schemas.json is stale. Regenerate:\n"
                  + "  node extension/test/schemas.gen.js");
    process.exit(1);
  }
  console.log("schemas.json is current");
} else {
  fs.writeFileSync(target, text);
  console.log("wrote", path.relative(process.cwd(), target));
}
