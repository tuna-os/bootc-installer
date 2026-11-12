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

// The `error` event: the last one is kept as {message, code, field,
// step_id, disk_changed, cleanup}, and the failure page's lines.
{
  const fixture = JSON.parse(
    readFileSync(join(here, "..", "..", "..", "shared", "progress", "error-cases.json"), "utf8"),
  );
  if (fixture.cases.length < 6) throw new Error("error-cases.json has too few cases");
  for (const c of fixture.cases) {
    const state = lib.newState();
    c.events.forEach((event, i) => {
      const bar = lib.advance(state, event);
      if (Math.abs(bar - c.bar[i]) > 1e-6) {
        console.error(`FAIL error-cases ${c.name} event ${i}: bar ${bar} want ${c.bar[i]}`);
        failures++;
      }
    });
    if (JSON.stringify(state.error) !== JSON.stringify(c.error)) {
      console.error(`FAIL error-cases ${c.name}: ${JSON.stringify(state.error)} want ${JSON.stringify(c.error)}`);
      failures++;
    }
    // The failure page's copy keys (tuna-os/fisherman#449).
    const lines = lib.failureLines(state.error);
    if (JSON.stringify(lines) !== JSON.stringify(c.lines)) {
      console.error(`FAIL error-cases ${c.name} lines: ${JSON.stringify(lines)} want ${JSON.stringify(c.lines)}`);
      failures++;
    }
  }
  console.log(`ok: ${fixture.cases.length} cases against shared/progress/error-cases.json`);
}

// shared/progress/receipt-cases.json: the receipt kept, the bar unmoved, and
// the done page's keys (#269).
{
  const fixture = JSON.parse(
    readFileSync(join(here, "..", "..", "..", "shared", "progress", "receipt-cases.json"), "utf8"),
  );
  const copyKeys = JSON.parse(
    readFileSync(join(here, "..", "..", "..", "shared", "branding", "copy-defaults.json"), "utf8"),
  );
  if (fixture.cases.length < 15) throw new Error("receipt-cases.json has too few cases");
  for (const c of fixture.cases) {
    const state = lib.newState();
    c.events.forEach((event, i) => {
      const bar = lib.advance(state, event);
      if (Math.abs(bar - c.bar[i]) > 1e-6) {
        console.error(`FAIL receipt-cases ${c.name} event ${i}: bar ${bar} want ${c.bar[i]}`);
        failures++;
      }
    });
    if (JSON.stringify(state.receipt) !== JSON.stringify(c.receipt)) {
      console.error(`FAIL receipt-cases ${c.name}: ${JSON.stringify(state.receipt)} want ${JSON.stringify(c.receipt)}`);
      failures++;
    }
    const lines = lib.receiptLines(state.receipt, (k) => k in copyKeys);
    if (JSON.stringify(lines) !== JSON.stringify(c.done_lines)) {
      console.error(`FAIL receipt-cases ${c.name} lines: ${JSON.stringify(lines)} want ${JSON.stringify(c.done_lines)}`);
      failures++;
    }
  }
  console.log(`ok: ${fixture.cases.length} cases against shared/progress/receipt-cases.json`);
}

// shared/probe/source-reuse-cases.json: the recipe after the pick, and the
// validate fragment (#267). The item itself is the Go backend's
// (installer/sourcecheck_test.go).
{
  const fixture = JSON.parse(
    readFileSync(join(here, "..", "..", "..", "shared", "probe", "source-reuse-cases.json"), "utf8"),
  );
  let offered = 0;
  const deep = (v) => Array.isArray(v) ? v.map(deep)
    : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, deep(v[k])])) : v;
  const sorted = (v) => JSON.stringify(deep(v));
  for (const c of fixture.cases) {
    if (!c.expected) continue;
    offered++;
    const ref = c.update_ref;
    const base = {
      disk: "/dev/vda", filesystem: "xfs", encryption: { type: "none", passphrase: "" },
      image: ref, targetImgref: ref, composeFsBackend: false, hostname: "workstation",
    };
    const recipe = lib.applyReuse(base, c.expected);
    if (sorted(recipe) !== sorted(c.recipe)) {
      console.error(`FAIL source-reuse ${c.name}: ${JSON.stringify(recipe)} want ${JSON.stringify(c.recipe)}`);
      failures++;
    }
    const fragment = lib.reuseFragment(recipe);
    if (sorted(fragment) !== sorted(c.fragment)) {
      console.error(`FAIL source-reuse ${c.name} fragment: ${JSON.stringify(fragment)}`);
      failures++;
    }
    if (lib.plainRef(ref) !== c.expected.ref) {
      console.error(`FAIL source-reuse ${c.name} plainRef`);
      failures++;
    }
  }
  if (offered < 3) throw new Error("source-reuse-cases.json offers too few items");
  console.log(`ok: ${offered} offered items against shared/probe/source-reuse-cases.json`);
}

// shared/progress/outcome-cases.json: the exit code decides (#269).
{
  const fixture = JSON.parse(
    readFileSync(join(here, "..", "..", "..", "shared", "progress", "outcome-cases.json"), "utf8"),
  );
  for (const c of fixture.cases) {
    const got = lib.installOutcome(c.exit_code, c.cancel_requested);
    if (got !== c.outcome) {
      console.error(`FAIL outcome-cases ${c.name}: ${got} want ${c.outcome}`);
      failures++;
    }
  }
  console.log(`ok: ${fixture.cases.length} cases against shared/progress/outcome-cases.json`);
}

// shared/progress/source-reuse-cases.json (#267): the copy of this
// computer's system before the first step, its lines, the cancel question,
// and a bar that the copy does not move.
{
  const fixture = JSON.parse(
    readFileSync(join(here, "..", "..", "..", "shared", "progress", "source-reuse-cases.json"), "utf8"),
  );
  const copyKeys = JSON.parse(
    readFileSync(join(here, "..", "..", "..", "shared", "branding", "copy-defaults.json"), "utf8"),
  );
  if (fixture.cases.length < 15) throw new Error("source-reuse-cases.json has too few cases");
  const sorted = (v) => JSON.stringify(v, v && typeof v === "object" ? Object.keys(v).sort() : undefined);
  for (const c of fixture.cases) {
    const state = lib.newState();
    c.events.forEach((event, i) => {
      const bar = lib.advance(state, event);
      if (Math.abs(bar - c.bar[i]) > 1e-6) {
        console.error(`FAIL source-reuse-cases ${c.name} event ${i}: bar ${bar} want ${c.bar[i]}`);
        failures++;
      }
    });
    if (sorted(state.sourceReuse) !== sorted(c.source_reuse)) {
      console.error(`FAIL source-reuse-cases ${c.name}: ${JSON.stringify(state.sourceReuse)} want ${JSON.stringify(c.source_reuse)}`);
      failures++;
    }
    const lines = lib.sourceReuseLines(state.sourceReuse, (k) => k in copyKeys);
    if (JSON.stringify(lines) !== JSON.stringify(c.lines)) {
      console.error(`FAIL source-reuse-cases ${c.name} lines: ${JSON.stringify(lines)} want ${JSON.stringify(c.lines)}`);
      failures++;
    }
    if (lib.copyCancel(state) !== c.copy_cancel) {
      console.error(`FAIL source-reuse-cases ${c.name} copy_cancel`);
      failures++;
    }
  }
  console.log(`ok: ${fixture.cases.length} cases against shared/progress/source-reuse-cases.json`);
}

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
