import { chromium } from '@playwright/test'
import { spawn } from 'node:child_process'
import { setTimeout as sleep } from 'node:timers/promises'
import { resolve } from 'node:path'

async function run() {
  console.log('Starting vite preview on port 5195...')
  const preview = spawn('npx', ['vite', 'preview', '--port', '5195', '--host', '127.0.0.1'], {
    cwd: resolve(import.meta.dirname, '..'),
    stdio: 'inherit',
  })

  try {
    await sleep(2000)
    console.log('Launching headless Chromium with /usr/bin/google-chrome...')
    const browser = await chromium.launch({
      executablePath: '/usr/bin/google-chrome',
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--headless=new'],
    })

    const context = await browser.newContext({
      viewport: { width: 1440, height: 1080 },
    })

    // Set signed-in state in storage before load
    await context.addInitScript(() => {
      try {
        localStorage.setItem('xibalba-cortex.signed-in', '1')
        sessionStorage.setItem('xibalba-cortex.signed-in', '1')
      } catch (e) {
        console.error(e)
      }
    })

    const page = await context.newPage()

    page.on('console', msg => console.log('PAGE LOG:', msg.text()))
    page.on('pageerror', err => console.log('PAGE ERROR:', err.message))

    console.log('Navigating directly to http://127.0.0.1:5195/#entities...')
    await page.goto('http://127.0.0.1:5195/#entities', { waitUntil: 'networkidle' })
    await sleep(3000)

    console.log('PAGE URL:', page.url())
    console.log('PAGE BODY PREVIEW:', (await page.innerText('body')).slice(0, 500))

    await page.screenshot({
      path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_now.png',
      fullPage: true,
    })

    // Click Discovery Studio tab
    console.log('Switching to Discovery Studio tab...')
    const studioTab = page.locator('button', { hasText: /Discovery Studio/i }).first()
    if (await studioTab.isVisible()) {
      await studioTab.click()
      await sleep(1000)

      // Screenshot 1: Connectors Tab
      console.log('Capturing screen_cortex_connectors.png...')
      await page.screenshot({
        path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_cortex_connectors.png',
        fullPage: true,
      })

      // Switch to Active Inference
      console.log('Switching to Active Inference tab...')
      const inferenceTab = page.locator('button', { hasText: /Active Inference & Discovery/i }).first()
      await inferenceTab.click()
      await sleep(1000)
      console.log('Capturing screen_cortex_inference.png...')
      await page.screenshot({
        path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_cortex_inference.png',
        fullPage: true,
      })

      // Switch to AIS Reward Simulator
      console.log('Switching to AIS Graph Reward Engine tab...')
      const rewardTab = page.locator('button', { hasText: /AIS Graph Reward Engine/i }).first()
      await rewardTab.click()
      await sleep(1000)

      // Click Verified Grounding preset
      const verifiedBtn = page.locator('button', { hasText: /1\. Verified Grounding/i }).first()
      if (await verifiedBtn.isVisible()) {
        await verifiedBtn.click()
        await sleep(500)
      }

      console.log('Capturing screen_discovery_studio.png...')
      await page.screenshot({
        path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_discovery_studio.png',
        fullPage: true,
      })
      console.log('All screenshots captured successfully!')
    } else {
      console.log('Discovery Studio tab was not found on this view.')
    }

    await browser.close()
  } finally {
    preview.kill()
  }
}

run().catch((err) => {
  console.error('Validation failed:', err)
  process.exit(1)
})
