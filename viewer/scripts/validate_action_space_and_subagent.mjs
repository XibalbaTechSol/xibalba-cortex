import { chromium } from 'playwright'

async function run() {
  console.log('Connecting to http://localhost:5195/#graph...')
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
    await page.goto('http://localhost:5195/#graph')
    await page.waitForTimeout(3000)

    // Capture main graph with dataset selector
    await page.screenshot({ path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_cortex_action_space_graph.png' })
    console.log('Captured screen_cortex_action_space_graph.png')

    // Navigate to Entities page
    console.log('Navigating to http://localhost:5195/#entities...')
    await page.goto('http://localhost:5195/#entities')
    await page.waitForTimeout(2000)

    // Click Discovery Studio toggle button
    const studioBtn = page.locator('button:has-text("Discovery Studio")')
    if (await studioBtn.isVisible()) {
      await studioBtn.click()
      await page.waitForTimeout(1000)
    }

    // Click Inference Subagent tab
    const subagentTab = page.locator('button:has-text("Inference Subagent")')
    if (await subagentTab.isVisible()) {
      await subagentTab.click()
      await page.waitForTimeout(1000)
      await page.screenshot({ path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_cortex_inference_subagent.png' })
      console.log('Captured screen_cortex_inference_subagent.png')

      // Click Synthesize Session
      const synthBtn = page.locator('button:has-text("Synthesize Session & Extract Action Space")')
      if (await synthBtn.isVisible()) {
        await synthBtn.click()
        await page.waitForTimeout(4000)
        await page.screenshot({ path: '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480/screen_cortex_inference_subagent_result.png' })
        console.log('Captured screen_cortex_inference_subagent_result.png')
      }
    }

  } finally {
    await browser.close()
  }
}

run().catch((err) => {
  console.error(err)
  process.exit(1)
})
