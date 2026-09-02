#!/usr/bin/env node
// Parse every ```mermaid block in a markdown file the way GitHub does.
//
// A malformed diagram renders on GitHub as a red "Unable to render rich display" box --
// worse than no diagram, and invisible from the markdown. This catches it before push.
//
// Needs two packages the repo otherwise does not use, so it is deliberately not wired
// into `npm test`:
//
//     npm install --no-save mermaid jsdom
//     node scripts/check-mermaid.mjs ARCHITECTURE.md
//
// The zero-dependency half of this check lives in evals/test_3_page_cannot_lie.py and
// runs every time, catching the entity and nested-quote cases that actually bit.
import fs from "node:fs";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { pretendToBeVisual: true });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, "navigator",
                      { value: dom.window.navigator, configurable: true });
globalThis.Element = dom.window.Element;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.SVGElement = dom.window.SVGElement;

// GitHub decodes HTML entities in the fenced block BEFORE handing it to mermaid.
// Parsing the raw text instead lets &quot; sail through as five harmless characters --
// which is exactly how a diagram that renders as an error box on GitHub passed here.
const decode = (t) => t
  .replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'")
  .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&");

const file = process.argv[2];
if (!file) { console.error("usage: check-mermaid.mjs <file.md>"); process.exit(2); }
const md = fs.readFileSync(file, "utf8");
const blocks = [...md.matchAll(/```mermaid\n([\s\S]*?)```/g)].map((m) => decode(m[1]));
if (!blocks.length) { console.log("no mermaid blocks found"); process.exit(0); }

const mermaid = (await import("mermaid")).default;
mermaid.initialize({ startOnLoad: false });
let bad = 0;
for (const [i, src] of blocks.entries()) {
  try {
    await mermaid.parse(src);
    console.log(`  block ${i + 1}: parses`);
  } catch (e) {
    bad++;
    console.log(`  block ${i + 1}: FAILS -- ${String(e.message || e).split("\n").slice(0, 3).join(" | ")}`);
  }
}
console.log(bad ? `${bad} diagram(s) would render as an error box on GitHub`
                : "all diagrams parse");
process.exit(bad ? 1 : 0);
