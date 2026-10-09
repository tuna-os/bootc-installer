// Feeds shared/progress/fraction-cases.json and overall-pct-cases.json
// through ui/progress.js, and checks its step labels.
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

function replay(file, minCases) {
  const fixture = JSON.parse(
    readFileSync(join(here, "..", "..", "..", "shared", "progress", file), "utf8"),
  );
  if (fixture.cases.length < minCases) throw new Error(`${file} has too few cases`);
  let failures = 0;
  for (const c of fixture.cases) {
    const state = lib.newState();
    c.events.forEach((event, i) => {
      const bar = lib.advance(state, event);
      if (Math.abs(bar - c.bar[i]) > 1e-6) {
        console.error(`FAIL ${file} ${c.name} event ${i}: bar ${bar} want ${c.bar[i]}`);
        failures++;
      }
    });
  }
  console.log(`${failures ? "FAIL" : "ok"}: ${fixture.cases.length} cases against shared/progress/${file}`);
  return failures;
}

let failures = replay("fraction-cases.json", 5);
// fisherman's overall_pct is the bar; an event without it falls back.
failures += replay("overall-pct-cases.json", 3);

// Step labels: the copy key step_<step_id>, else fisherman's step_name.
const copy = { step_flatpaks: "Installing your apps…" };
const lookup = (id) => copy["step_" + id] || "";
const labels = [
  [{ type: "step", step_name: "Copying system Flatpaks", step_id: "flatpaks" }, "Installing your apps…"],
  [{ type: "step", step_name: "Polishing the hull", step_id: "polish_hull" }, "Polishing the hull"],
  [{ type: "step", step_name: "Copying system Flatpaks" }, "Copying system Flatpaks"],
  [{ type: "step" }, ""],
];
for (const [event, want] of labels) {
  const got = lib.stepLabel(event, lookup);
  if (got !== want) {
    console.error(`FAIL stepLabel(${JSON.stringify(event)}): ${JSON.stringify(got)} want ${JSON.stringify(want)}`);
    failures++;
  }
}
if (failures) process.exit(1);
console.log(`ok: ${labels.length} step labels`);
