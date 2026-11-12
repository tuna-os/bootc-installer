// Runs ui/recipe.js, the recipe half of installer.qml, without a QML engine.
//
// stdin: {"leaf": <a leaf of the backend's `catalog` output>, "choices": <the
// arguments of build() other than imageKeys>}. stdout: the recipe that the
// wizard hands to the backend's `install`, as JSON. installer/compliance_test.go
// runs this for each case of shared/recipe/fixtures/compliance.json.
//
//     node tests/recipe-build.mjs < input.json
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "..", "ui", "recipe.js"), "utf8")
  .split("\n")
  .filter((l) => !l.startsWith(".pragma"))
  .join("\n");
const lib = {};
vm.runInNewContext(src, lib);

const input = JSON.parse(readFileSync(0, "utf8"));
const choices = Object.assign({}, input.choices, { imageKeys: lib.leafKeys(input.leaf) });
process.stdout.write(JSON.stringify(lib.build(choices)) + "\n");
