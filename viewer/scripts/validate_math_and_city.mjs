import { chromium } from 'playwright'
import { spawn } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')

async function run() {
  console.log('Starting preview server...')
  const preview = spawn('npx', ['vite', 'preview', '--port', '4173'], {
    cwd: ROOT,
    stdio: 'pipe',
  })

  await new Promise((resolve) => setTimeout(resolve, 2000))

  const browser = await chromium.launch({
    headless: true,
    args: ['--use-gl=angle', '--use-angle=gl', '--enable-webgl', '--ignore-gpu-blocklist'],
  })

  try {
    const context = await browser.newContext({
      viewport: { width: 1600, height: 950 },
    })

    // Set signed-in state
    await context.addInitScript(() => {
      localStorage.setItem('xibalba-cortex.signed-in', '1')
    })

    const page = await context.newPage()
    console.log('Navigating to http://localhost:4173/#graph...')
    await page.goto('http://localhost:4173/#graph')
    await page.waitForTimeout(3000)

    // Capture main 3D graph
    await page.screenshot({ path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_3d_graph_lattice.png' })
    console.log('Captured screen_3d_graph_lattice.png')

    // Click Math button
    const mathBtn = page.locator('button:has-text("📐 Math")')
    if (await mathBtn.isVisible()) {
      await mathBtn.click()
      await page.waitForTimeout(1500)
      await page.screenshot({ path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_graph_math_studio.png' })
      console.log('Captured screen_graph_math_studio.png')

      // Switch tab to Cosine Similarity
      const cosineTab = page.locator('button:has-text("Cosine Similarity")')
      if (await cosineTab.isVisible()) {
        await cosineTab.click()
        await page.waitForTimeout(600)
        await page.screenshot({ path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_graph_math_cosine.png' })
        console.log('Captured screen_graph_math_cosine.png')
      }

      // Switch tab to Spectral Theory
      const spectralTab = page.locator('button:has-text("Spectral Theory")')
      if (await spectralTab.isVisible()) {
        await spectralTab.click()
        await page.waitForTimeout(600)
        await page.screenshot({ path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_graph_math_spectral.png' })
        console.log('Captured screen_graph_math_spectral.png')
      }

      // Switch tab to Centrality Leaderboard
      const centralityTab = page.locator('button:has-text("Centrality Leaderboard")')
      if (await centralityTab.isVisible()) {
        await centralityTab.click()
        await page.waitForTimeout(600)
        await page.screenshot({ path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_graph_math_centrality.png' })
        console.log('Captured screen_graph_math_centrality.png')
      }

      // Close Math Studio
      const closeBtn = page.locator('button[title*="Close Math Studio"]')
      if (await closeBtn.isVisible()) {
        await closeBtn.click()
        await page.waitForTimeout(600)
      }
    }

    // Toggle Immersion Mode
    await page.keyboard.press('z')
    await page.waitForTimeout(1000)
    await page.screenshot({ path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_zen_immersion.png' })
    console.log('Captured screen_zen_immersion.png')

  } finally {
    await browser.close()
    preview.kill()
  }
}

run().catch((err) => {
  console.error(err)
  process.exit(1)
})
