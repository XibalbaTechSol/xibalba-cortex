import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
const require = createRequire(new URL('../package.json', import.meta.url))
let chromium
try { ({ chromium } = require('playwright')) } catch { ({ chromium } = require('@playwright/test')) }
const dir = process.cwd() + '/canvas-publish/project'
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium' })
for (const n of process.argv.slice(2)) {
  const src = readFileSync(`${dir}/${n}.dc.html`, 'utf8')
  const w = Number(/--board-w: (\d+)px/.exec(src)[1]); const h = Number(/--board-h: (\d+)px/.exec(src)[1])
  const page = await browser.newPage({ viewport: { width: w, height: h } })
  await page.route('**/_blob/**', (r) => r.fulfill({ status: 200, contentType: 'image/png', body: Buffer.alloc(0) }))
  await page.route('https://fonts.googleapis.com/**', (r) => r.abort())
  await page.goto(`file://${dir}/${n}.dc.html`); await page.waitForTimeout(600)
  await page.screenshot({ path: `boards-png/render-${n}.png` }); await page.close()
}
await browser.close()
