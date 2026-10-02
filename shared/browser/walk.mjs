// Drive a frontend that is already on a Broadway display, through a browser.
//
// What this buys over the Xvfb capture harnesses: the pixels are produced by
// the same renderer a user would get, but they arrive in a browser, so the
// same Playwright run that screenshots a page can also click it, type into
// it, trace it and record it. The Xvfb harnesses can only look.
//
// Two facts about Broadway shape everything below.
//
//   1. Text is never in the DOM. GTK rasterises glyphs and Broadway ships
//      them as <img> textures, so there is no accessibility tree and
//      getByRole/getByText cannot work. Assertions are about geometry and
//      pixels, and widgets are found by colour and position, not by label.
//   2. GTK4 and GTK3 do not render alike. GTK4 Broadway emits a tree of
//      positioned <div>s (one per render node) plus texture <img>s, so the
//      DOM carries real geometry. GTK3 Broadway paints into a single
//      <canvas>, so it carries none. Geometry assertions therefore run on
//      GTK4 only, and the code says so rather than silently passing.
//
// Niri is not Broadway at all. Its wizard is compiled to WebAssembly with Qt
// (frontends/niri/tests/wasm), so the page itself is the app, and pages are
// requested through window.niri rather than through two files. It also paints
// one <canvas>, but unlike Broadway it can read its own scene, so it reports
// the visible page's text and the capture harness's own checks, and those are
// asserted too.
//
// Usage: node walk.mjs --port 8085 --cmd <file> --state <file> --out <dir>
//                      [--toolkit gtk4|gtk3] [--name gnome]
//        node walk.mjs --url http://127.0.0.1:8090/ --toolkit qt-wasm
//                      --out <dir> --name niri

import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

// Resolve Playwright from wherever it is: a local node_modules, a global
// install, or an explicit path. ESM `import` ignores NODE_PATH, and a global
// install is the normal case on a machine that is not a Node project, so a
// bare `import 'playwright'` would work only for whoever happened to run
// `npm install` in this directory first.
const require = createRequire(import.meta.url);
function loadPlaywright() {
  const candidates = [
    process.env.PLAYWRIGHT_MODULE,
    'playwright',
    '/opt/node22/lib/node_modules/playwright',
    '/usr/lib/node_modules/playwright',
    '/usr/local/lib/node_modules/playwright',
  ].filter(Boolean);
  for (const c of candidates) {
    try { return require(c); } catch { /* try the next one */ }
  }
  console.error('walk.mjs: playwright not found. Install it with ' +
                '`npm install playwright`, or set PLAYWRIGHT_MODULE to its path.');
  process.exit(127);
}
const { chromium } = loadPlaywright();

function arg(flag, fallback) {
  const i = process.argv.indexOf(flag);
  return i === -1 ? fallback : process.argv[i + 1];
}

const port = Number(arg('--port', '8085'));
const cmdFile = arg('--cmd');
const stateFile = arg('--state');
const outDir = arg('--out', 'browser-shots');
const toolkit = arg('--toolkit', 'gtk4');
const frontend = arg('--name', 'gnome');
const url = arg('--url');
const wasm = toolkit === 'qt-wasm';

if (wasm ? !url : (!cmdFile || !stateFile)) {
  console.error(wasm ? 'walk.mjs: --url is required for qt-wasm'
                     : 'walk.mjs: --cmd and --state are required');
  process.exit(2);
}

fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch({ args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1200, height: 820 } });
if (wasm) {
  // The QML errors arrive on the console, and nowhere else.
  page.on('console', m => { if (m.type() === 'error' || /QML|qrc:/.test(m.text())) console.log(`  [console] ${m.text()}`); });
  page.on('pageerror', e => console.log(`  [pageerror] ${e.message}`));
}
await page.goto(url ?? `http://127.0.0.1:${port}/`, { waitUntil: 'networkidle' });

// Two transports, one protocol: ask for a page, then read back
// {pages, current} until the app says it has drawn it.
let readState, requestPage;
if (wasm) {
  // Downloading and compiling some 30 MB of wasm takes a while on a runner.
  await page.waitForFunction(() => window.niri && (window.niri.ready || window.niri.error),
                             null, { timeout: 120_000 });
  const error = await page.evaluate(() => window.niri.error);
  if (error) {
    console.error(`walk.mjs: ${frontend} did not start: ${error}`);
    process.exit(1);
  }
  readState = () => page.evaluate(() => window.niri.state());
  requestPage = name => page.evaluate(n => window.niri.show(n), name);
} else {
  readState = async () => JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  requestPage = async name => fs.writeFileSync(cmdFile, name);
}

// The presenter writes the page list before it is ready for requests.
let pages = null;
for (let i = 0; i < 100; i++) {
  try {
    const s = await readState();
    if (s.error) {
      console.error(`walk.mjs: ${frontend}: ${s.error}`);
      process.exit(1);
    }
    if (s.pages && s.pages.length) { pages = s.pages; break; }
  } catch { /* not written yet */ }
  await new Promise(r => setTimeout(r, 200));
}
if (!pages) {
  console.error(`walk.mjs: ${frontend} never published a page list`);
  process.exit(1);
}

// Broadway connects over a WebSocket after load and the first frame follows.
// Waiting for something on screen beats a fixed sleep: a slow runner would
// otherwise screenshot a blank page and call it a render.
// GTK4 fills the DOM with positioned divs; GTK3 paints one canvas. Waiting
// for "something with area is on screen" covers both without pretending they
// render alike.
await page.waitForFunction(
  () => {
    for (const el of document.querySelectorAll('div,img,canvas')) {
      const r = el.getBoundingClientRect();
      if (r.width > 100 && r.height > 100) return true;
    }
    return false;
  },
  null, { timeout: 30_000 },
);
await page.waitForTimeout(1500);

const findings = [];
let previous = null;

for (const name of pages) {
  await requestPage(name);
  let settled = false, state = null;
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(150);
    try {
      state = await readState();
      if (state.current === name) { settled = true; break; }
    } catch { /* mid-write */ }
  }
  await page.waitForTimeout(500);

  const file = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: file });
  const bytes = fs.statSync(file).size;

  const geometry = toolkit === 'gtk4'
    ? await page.evaluate(() => {
        let surface = null, nodes = 0;
        for (const el of document.querySelectorAll('div,img')) {
          const r = el.getBoundingClientRect();
          if (r.width > 4 && r.height > 4) nodes++;
          if (r.width > 400 && r.height > 300 &&
              (!surface || r.width * r.height > surface.w * surface.h)) {
            surface = { x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height) };
          }
        }
        return { surface, nodes };
      })
    : { surface: null, nodes: null };   // GTK3 and Qt paint one canvas: no geometry

  findings.push({
    name, png: file, bytes, settled,
    nodes: geometry.nodes, surface: geometry.surface,
    distinct: previous === null ? true : bytes !== previous,
    // Only Qt for wasm can say what it drew; Broadway ships text as pixels.
    ...(wasm && settled ? { text: state.text ?? '', checks: state.checks ?? {} } : {}),
  });
  previous = bytes;

  const geo = geometry.surface
    ? `${geometry.surface.w}x${geometry.surface.h}`
    : (toolkit === 'gtk4' ? 'NO SURFACE' : 'canvas');
  console.log(`  ${name.padEnd(14)} ${String(bytes).padStart(7)}B  ` +
              `nodes=${String(geometry.nodes ?? '-').padStart(4)}  ${geo}` +
              `${settled ? '' : '  (NEVER SETTLED)'}`);
}

await browser.close();

// ── the checks ───────────────────────────────────────────────────────────────
// A blank page still writes a valid PNG, so bytes alone prove nothing. Three
// things together do: the app acknowledged the page, the image is not tiny,
// and it differs from the page before it. That last one is what catches a
// wizard that silently stopped advancing -- the failure this harness exists
// to notice, and the one a per-page screenshot on its own cannot see.
const failures = [];
for (const f of findings) {
  if (!f.settled) failures.push(`${f.name}: the app never confirmed the page`);
  if (f.bytes < 4000) failures.push(`${f.name}: ${f.bytes}B PNG, nothing drawn`);
  if (!f.distinct) failures.push(`${f.name}: byte-identical to the previous page`);
  if (toolkit === 'gtk4' && !f.surface) failures.push(`${f.name}: no GTK surface in the DOM`);
  if (wasm && f.settled) {
    if (!f.text.trim()) failures.push(`${f.name}: the visible page has no text`);
    for (const [check, r] of Object.entries(f.checks)) {
      if (!r.ok) failures.push(`${f.name}: ${check}: ${r.why}`);
    }
  }
}
if (!findings.length) failures.push('captured no pages');

fs.writeFileSync(
  path.join(outDir, `browser-walkthrough-${frontend}.json`),
  JSON.stringify({
    frontend, toolkit, port,
    harness: wasm ? 'shared/browser/walk.mjs (Qt for WebAssembly + Playwright)'
                  : 'shared/browser/walk.mjs (Broadway + Playwright)',
    pages: findings,
    ok: failures.length === 0,
  }, null, 2) + '\n',
);

if (failures.length) {
  for (const msg of failures) console.error(`FAIL: ${msg}`);
  process.exit(1);
}
console.log(`  ${findings.length} pages captured through the browser`);
