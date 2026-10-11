import { createRequire } from 'node:module'
import { readdirSync, readFileSync, writeFileSync } from 'node:fs'
const require = createRequire(new URL('../package.json', import.meta.url))
let chromium
try { ({ chromium } = require('playwright')) } catch { ({ chromium } = require('@playwright/test')) }
const dir = process.cwd() + '/canvas-publish/project'
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium' })
const out = {}
for (const f of readdirSync(dir).filter((x) => x.startsWith('Planned') && x.endsWith('.dc.html'))) {
  const src = readFileSync(`${dir}/${f}`, 'utf8')
  const w = Number(/--board-w: (\d+)px/.exec(src)[1]); const h = Number(/--board-h: (\d+)px/.exec(src)[1])
  const page = await browser.newPage({ viewport: { width: w, height: h } })
  await page.route('**/_blob/**', (r) => r.fulfill({ status: 200, contentType: 'image/png', body: Buffer.alloc(0) }))
  await page.route('https://fonts.googleapis.com/**', (r) => r.abort())
  await page.goto(`file://${dir}/${f}`); await page.waitForTimeout(500)
  // the content's natural height: grow the viewport until nothing is taller than it
  let vh = h
  for (let i = 0; i < 5; i++) {
    const sh = await page.evaluate(() => document.documentElement.scrollHeight)
    if (sh <= vh + 1) break
    vh = sh; await page.setViewportSize({ width: w, height: vh }); await page.waitForTimeout(300)
  }
  const stem = f.replace('.dc.html', '')
  console.log(stem, 'declared', h, 'natural', vh)
  out[stem] = vh
  await page.close()
}
writeFileSync('measured.json', JSON.stringify(out)); await browser.close()
