// Runs ui/plan.js, the plan half of installer.qml, without a QML engine.
//
// stdin: {"view": <the backend's `plan` output>, "recipe": <an install
// recipe>, "copy": {key: line}}. stdout: {"rows": rows(view, text),
// "recipe": bind(recipe, view)}, as JSON. `text` fills the placeholders as
// installer.qml's root.text() does. installer/plan_test.go runs this for
// fisherman's golden plans.
//
//     node tests/plan-rows.mjs < input.json
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "..", "ui", "plan.js"), "utf8")
  .split("\n")
  .filter((l) => !l.startsWith(".pragma"))
  .join("\n");
const lib = {};
vm.runInNewContext(src, lib);

const input = JSON.parse(readFileSync(0, "utf8"));
const copy = input.copy || {};
function text(key, values) {
  let line = copy[key] || "";
  for (const k in values || {}) line = line.split("{" + k + "}").join(values[k]);
  return line;
}
process.stdout.write(
  JSON.stringify({ rows: lib.rows(input.view, text), recipe: lib.bind(input.recipe, input.view) }) + "\n",
);
