import { test, expect, type Page } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'

async function openGraph3D(page: Page) {
  await page.addInitScript(() => {
    sessionStorage.setItem('xibalba-cortex.signed-in', '1')
    localStorage.setItem('xibalba-cortex.console-settings', JSON.stringify({ graphMode: '3d' }))
  })
  await stubConsoleApi(page)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.xc')).toBeVisible({ timeout: 20000 })
  const canvas = page.locator('.xc-canvas-win canvas')
  await expect(canvas).toBeVisible({ timeout: 20000 })
  await expect(canvas).toHaveAttribute('data-node-count', /[1-9]/, { timeout: 20000 })
  return canvas
}

test.describe('Zen Mode Controls & Inner Sanctum Room E2E', () => {
  test('zen immersion activation, d-pad controls, presets, and inner sanctum room flight', async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 950 })
    await openGraph3D(page)

    // 1. Activate Zen Immersion Mode via Z button
    const zenBtn = page.locator('button[title*="Zen Immersion Mode"]')
    await expect(zenBtn).toBeVisible()
    await zenBtn.click()

    const shell = page.locator('.xc-shell')
    await expect(shell).toHaveAttribute('data-immersion', 'true')

    // 2. Verify Zen Flight Cockpit & Topbar are visible
    const zenTopbar = page.locator('.xc-zen-topbar')
    await expect(zenTopbar).toBeVisible()
    await expect(zenTopbar).toContainText('ZEN IMMERSION')

    const cockpit = page.locator('.xc-zen-flight-cockpit')
    await expect(cockpit).toBeVisible()
    await expect(cockpit).toContainText('FLIGHT D-PAD')

    const artifactDir = '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480'
    await page.screenshot({ path: `${artifactDir}/zen_flight_cockpit.png` })

    // 3. Test D-Pad direction buttons
    const upBtn = cockpit.locator('.xc-zen-dpad-up')
    const leftBtn = cockpit.locator('.xc-zen-dpad-left')
    const rightBtn = cockpit.locator('.xc-zen-dpad-right')
    const downBtn = cockpit.locator('.xc-zen-dpad-down')
    const fitBtn = cockpit.locator('.xc-zen-dpad-center')

    await upBtn.click()
    await leftBtn.click()
    await rightBtn.click()
    await downBtn.click()
    await fitBtn.click()

    // 4. Test Mode Toggle between Orbit and Pan
    const modeToggle = cockpit.locator('.xc-zen-toggle-pill')
    await expect(modeToggle).toContainText('Mode: Orbit')
    await modeToggle.click()
    await expect(modeToggle).toContainText('Mode: Pan')
    await modeToggle.click()
    await expect(modeToggle).toContainText('Mode: Orbit')

    // 5. Test Camera Presets
    const isoPreset = cockpit.locator('.xc-zen-preset-btn', { hasText: '1 · ISO' })
    const topPreset = cockpit.locator('.xc-zen-preset-btn', { hasText: '2 · TOP' })
    const frontPreset = cockpit.locator('.xc-zen-preset-btn', { hasText: '3 · FRONT' })
    const sidePreset = cockpit.locator('.xc-zen-preset-btn', { hasText: '4 · SIDE' })

    await isoPreset.click()
    await topPreset.click()
    await frontPreset.click()
    await sidePreset.click()

    // 6. Test Keyboard Shortcuts Cheatsheet Drawer
    const keysToggle = zenTopbar.locator('button', { hasText: '⌨️ Keys' })
    await keysToggle.click()
    const shortcutsModal = page.locator('.xc-zen-shortcuts-modal')
    await expect(shortcutsModal).toBeVisible()
    await expect(shortcutsModal).toContainText('ZEN KEYBOARD NAVIGATION CHEATSHEET')
    await page.screenshot({ path: `${artifactDir}/zen_shortcuts_cheatsheet.png` })
    await keysToggle.click()
    await expect(shortcutsModal).not.toBeVisible()

    // 7. Cycle nodes with navigation arrow
    const nextNodeBtn = zenTopbar.locator('button[aria-label="Next node"]')
    await nextNodeBtn.click()

    // Wait for selected node label to appear in topbar
    const nodeLabel = zenTopbar.locator('.xc-zen-node-label')
    await expect(nodeLabel).toBeVisible()

    // 8. Dive inside node into Inner Sanctum Room
    const enterRoomBtn = zenTopbar.locator('.xc-zen-action-btn--dive')
    if (await enterRoomBtn.isVisible()) {
      await enterRoomBtn.click()
    } else {
      await page.keyboard.press('Enter')
    }

    // 9. Verify Inner Sanctum Room Cockpit is rendered
    const roomCockpit = page.locator('.xc-room-cockpit')
    await expect(roomCockpit).toBeVisible({ timeout: 10000 })
    await expect(roomCockpit).toContainText('INNER WORLD SANCTUM')
    await page.waitForTimeout(1000)
    await page.screenshot({ path: `${artifactDir}/inner_sanctum_chamber.png` })

    // Verify Camera Directives
    const aimEastBtn = roomCockpit.locator('.xc-room-aim-btn', { hasText: 'Aim East' })
    await aimEastBtn.click()

    // 10. Test Tab 2: Novel Vector Representation
    const vectorTab = roomCockpit.locator('.xc-room-tab', { hasText: 'Vectors & Latent Tensors' })
    await vectorTab.click()
    await expect(roomCockpit).toContainText('NOVEL VECTOR REPRESENTATION')
    const quiverCards = roomCockpit.locator('.xc-room-quiver-card')
    await expect(quiverCards.first()).toBeVisible()
    await page.screenshot({ path: `${artifactDir}/inner_sanctum_vectors.png` })

    // 11. Test Tab 3: Novel Scalar Monoliths
    const scalarTab = roomCockpit.locator('.xc-room-tab', { hasText: 'Scalar Monoliths' })
    await scalarTab.click()
    await expect(roomCockpit).toContainText('Degree Centrality Obelisk')
    await expect(roomCockpit).toContainText('AIS Grounding Gyroscope')
    await expect(roomCockpit).toContainText('Dirichlet Topological Energy Pool')
    await page.screenshot({ path: `${artifactDir}/inner_sanctum_scalars.png` })

    // 12. Test Tab 4: Spatial Portals & Teleportation
    const portalsTab = roomCockpit.locator('.xc-room-tab', { hasText: 'Spatial Portals' })
    await portalsTab.click()
    await page.screenshot({ path: `${artifactDir}/inner_sanctum_portals.png` })

    const warpBtn = roomCockpit.locator('.xc-room-warp-btn').first()
    if (await warpBtn.isVisible()) {
      await warpBtn.click()
      await expect(roomCockpit).toBeVisible()
    }

    // 13. Ascend back to global orbit
    const ascendBtn = roomCockpit.locator('.xc-room-ascend-btn')
    await ascendBtn.click()
    await expect(roomCockpit).not.toBeVisible({ timeout: 5000 })

    // 14. Exit Zen Mode
    const exitZenBtn = zenTopbar.locator('.xc-zen-btn--exit')
    await exitZenBtn.click()
    await expect(shell).toHaveAttribute('data-immersion', 'false')
  })

  test('maximized knowledge graph layout with slim margins and dark-glass icon controls', async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 950 })
    await openGraph3D(page)

    // Verify workspace header is slim (34px)
    const header = page.locator('.xc-workspace-header')
    await expect(header).toBeVisible()
    const headerBox = await header.boundingBox()
    expect(headerBox?.height).toBeLessThanOrEqual(40)

    // Verify lens switch icons
    const lensIcons = page.locator('.xc-lens-icons')
    await expect(lensIcons).toBeVisible()
    const graphBtn = lensIcons.locator('button[aria-label="Graph"]')
    await expect(graphBtn).toBeVisible()

    // Verify glassy dark zoom stack
    const zoomStack = page.locator('.xc-zoom')
    await expect(zoomStack).toBeVisible()

    // Verify compact dataset bar
    const datasetSelect = page.locator('.xc-dataset-select')
    await expect(datasetSelect).toBeVisible()

    const artifactDir = '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480'
    await page.screenshot({ path: `${artifactDir}/maximized_knowledge_graph_canvas.png` })
  })

  test('healthcare researcher demo agent dropdown with custom DID and clinical latent space', async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 950 })
    await openGraph3D(page)

    // Check workspace dropdown contains custom DID option
    const wsSelect = page.locator('.xc-scope select.xc-input')
    await expect(wsSelect).toBeVisible()
    const demoOption = wsSelect.locator('option[value*="did:integrity:healthcare-researcher-latent-space-01"]')
    await expect(demoOption).toBeAttached()
    await expect(demoOption).toContainText('Healthcare Researcher')

    // Select the demo agent workspace
    const demoVal = await demoOption.getAttribute('value')
    if (demoVal) {
      await wsSelect.selectOption(demoVal)
    }

    // Verify dataset selector is aligned to healthcare_researcher
    const datasetSelect = page.locator('.xc-dataset-select')
    await expect(datasetSelect).toHaveValue('healthcare_researcher')

    const artifactDir = '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480'
    await page.screenshot({ path: `${artifactDir}/healthcare_researcher_demo_agent.png` })
  })

  test('similar memories in inspector renders properly without hosted unsupported error', async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 950 })
    await openGraph3D(page)

    // Switch to timeline lens and select an item to open inspector
    const timelineBtn = page.locator('.xc-lens-icons button[aria-label="Timeline"]')
    await expect(timelineBtn).toBeVisible()
    await timelineBtn.click()

    // Click a mark to open inspector
    const mark = page.locator('.xc-mark').first()
    await expect(mark).toBeVisible({ timeout: 10000 })
    await mark.click()

    const inspector = page.locator('.xc-inspector')
    await expect(inspector).toBeVisible({ timeout: 15000 })

    // Open Relations / Similar tab if present
    const relTab = inspector.locator('button.xc-tab', { hasText: 'Relations' })
    if (await relTab.isVisible()) {
      await relTab.click()
    }

    // Verify "The hosted edition does not offer this yet" is NEVER displayed
    await expect(inspector).not.toContainText('The hosted edition does not offer this yet')

    const artifactDir = '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480'
    await page.screenshot({ path: `${artifactDir}/similar_memories_inspector.png` })
  })
})
