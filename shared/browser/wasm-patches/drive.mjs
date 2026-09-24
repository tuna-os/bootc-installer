import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const browser = await chromium.launch({
  args: ['--no-sandbox', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'],
});
const page = await browser.newPage({ viewport: { width: 1000, height: 700 } });
page.on('pageerror', e => console.log('  [pageerror]', String(e).slice(0, 160)));
await page.goto('http://127.0.0.1:8099/', { waitUntil: 'load' });
await page.waitForTimeout(40000);
await page.screenshot({ path: 'step-1-welcome.png' });
// The wasm canvas is one opaque element: drive it like a user, at coordinates.
// "Get started" sits bottom-right at roughly (907, 651) in a 1000x700 window.
await page.mouse.click(907, 651);
await page.waitForTimeout(6000);
await page.screenshot({ path: 'step-2-after-click.png' });
console.log('clicked; canvas =', JSON.stringify(await page.evaluate(() =>
  [...document.querySelectorAll('canvas')].map(c => ({ w: c.width, h: c.height })))));
await browser.close();
