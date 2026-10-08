// Feeds shared/progress/fraction-cases.json through ui/progress.js.
//
// The fixture is generated from the canonical Python parser and pins the bar
// after every event; GNOME, XFCE, COSMIC and KDE test against the same file.
// ui/progress.js is a QML JavaScript library, so its `.pragma library` line
// is dropped and the rest runs as plain JavaScript.
//
//     node tests/progress-fraction-test.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "..", "ui", "progress.js"), "utf8")
  .split("\n")
  .filter((l) => !l.startsWith(".pragma"))
  .join("\n");
const lib = {};
vm.runInNewContext(src, lib);

const fixture = JSON.parse(
  readFileSync(join(here, "..", "..", "..", "shared", "progress", "fraction-cases.json"), "utf8"),
);
if (fixture.cases.length < 5) throw new Error("fixture has too few cases");

let failures = 0;
for (const c of fixture.cases) {
  const state = lib.newState();
  c.events.forEach((event, i) => {
    const bar = lib.advance(state, event);
    if (Math.abs(bar - c.bar[i]) > 1e-6) {
      console.error(`FAIL ${c.name} event ${i}: bar ${bar} want ${c.bar[i]}`);
      failures++;
    }
  });
}
if (failures) process.exit(1);
console.log(`ok: ${fixture.cases.length} cases match shared/progress/fraction-cases.json`);
