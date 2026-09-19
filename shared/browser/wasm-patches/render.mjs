import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const browser = await chromium.launch({
  args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader',
         '--ignore-gpu-blocklist', '--enable-webgl'],
});
const page = await browser.newPage({ viewport: { width: 1000, height: 700 } });
page.on('console', m => console.log(`  [console.${m.type()}] ${m.text()}`.slice(0, 300)));
page.on('pageerror', e => console.log(`  [pageerror] ${String(e).slice(0, 300)}`));

await page.goto('http://127.0.0.1:8099/', { waitUntil: 'load' });
await page.waitForTimeout(Number(process.argv[2] || 25000));

const state = await page.evaluate(() => ({
  status: window.__status,
  canvases: [...document.querySelectorAll('canvas')].map(c => ({
    w: c.width, h: c.height,
    cw: Math.round(c.getBoundingClientRect().width),
    ch: Math.round(c.getBoundingClientRect().height),
  })),
  webgl: (() => { try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch { return false; } })(),
  log: (window.__log || []).slice(-25),
}));
console.log('\nstatus :', state.status);
console.log('webgl  :', state.webgl);
console.log('canvas :', JSON.stringify(state.canvases));
console.log('log    :\n  ' + state.log.join('\n  '));
await page.screenshot({ path: 'cosmic-wasm.png' });
await browser.close();
