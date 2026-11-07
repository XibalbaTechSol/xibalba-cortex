const { chromium } = require('@playwright/test');
const fs = require('fs');

const TOKEN = fs.readFileSync('/tmp/cortex_token.txt', 'utf8').trim();
const BASE_URL = 'https://cortex-managed-pilot.onrender.com';
const ARTIFACT_DIR = '/home/xibalba/.gemini/antigravity-cli/brain/915d42e0-a7ed-43f0-a667-f2078843f480';

async function run() {
  const browser = await chromium.launch({
    headless: true,
    args: ['--use-gl=swiftshader', '--enable-webgl', '--no-sandbox', '--disable-setuid-sandbox']
  });
  const context = await browser.newContext({ viewport: { width: 1600, height: 960 } });

  // Route interception for bearer token injection and /api/managed/me mock
  await context.route('**/api/**', async (route) => {
    const url = route.request().url();
    if (url.includes('/api/managed/me') || url.includes('/api/auth/me')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          account: {
            id: 'acc-operator',
            email: 'operator@xibalba.solutions',
            status: 'active',
            email_verified: true,
            approval_status: 'approved'
          },
          entitlement: { tier: 'enterprise', writable: true },
          destinations: [
            'graph', 'timeline', 'memories', 'entities', 'sessions',
            'recall', 'review', 'integrity', 'operations', 'agents',
            'settings', 'billing'
          ],
          csrf_token: 'valid_operator_csrf'
        })
      });
      return;
    }
    const headers = { ...route.request().headers(), authorization: `Bearer ${TOKEN}` };
    await route.continue({ headers });
  });

  const page = await context.newPage();

  await page.addInitScript(() => {
    sessionStorage.setItem('xibalba-cortex.signed-in', '1');
    sessionStorage.setItem('xibalba-cortex.account', JSON.stringify({
      id: 'acc-operator',
      email: 'operator@xibalba.solutions',
      display_name: 'Xibalba Operator'
    }));
    sessionStorage.setItem('xibalba-cortex.active-agent', 'did:integrity:68fed1331613937555a59398223e8e87520a87dd0305aac4fd7ecdc32a14a861');
  });

  console.log('1. Navigating to Render managed UI: ' + BASE_URL + '/managed');
  await page.goto(`${BASE_URL}/managed`, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForSelector('.xc-workspace', { timeout: 15000 });
  await page.waitForTimeout(3000);

  console.log('2. Capturing 3D Graph Lattice...');
  await page.screenshot({ path: `${ARTIFACT_DIR}/render_live_3d_graph.png` });

  console.log('3. Switching dataset to Agent Action Space...');
  try {
    const select = page.locator('.xc-dataset-select');
    if (await select.isVisible()) {
      await select.selectOption('action_space');
      await page.waitForTimeout(3000);
    }
  } catch (err) {
    console.log('Dataset select error:', err);
  }
  await page.screenshot({ path: `${ARTIFACT_DIR}/render_live_action_space.png` });

  console.log('4. Opening Formal Graph Math Studio...');
  try {
    const mathBtn = page.locator("button[aria-label='Formal Graph Mathematics'], button.xc-zoom-text:has-text('fx')").first();
    if (await mathBtn.isVisible()) {
      await mathBtn.click();
      await page.waitForSelector('.xc-math-studio', { timeout: 10000 });
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `${ARTIFACT_DIR}/render_live_math_studio.png` });

      // Switch to Centrality tab and click a node link to select it
      const centralityTab = page.locator(".xc-math-studio button[role='tab']:has-text('Centrality')").first();
      if (await centralityTab.isVisible()) {
        await centralityTab.click({ force: true });
        await page.waitForTimeout(1000);
      }
      const nodeLink = page.locator('.xc-math-studio td button.xc-link').first();
      if (await nodeLink.isVisible()) {
        await nodeLink.click({ force: true });
        await page.waitForTimeout(1000);
      }

      // Close Math Studio via close button inside .xc-math-studio
      const closeBtn = page.locator(".xc-math-studio button[title*='Close Math Studio']").first();
      if (await closeBtn.isVisible()) {
        await closeBtn.click({ force: true });
      }
      await page.locator('.xc-math-studio').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(1000);
    } else {
      console.log('Math button not visible');
    }
  } catch (err) {
    console.log('Math studio error:', err);
  }

  console.log('5. Triggering Zen Immersion Mode...');
  try {
    const zenBtn = page.locator("button[aria-label='Toggle Zen Immersion Mode'], button.xc-zoom-text:has-text('Z')").first();
    if (await zenBtn.isVisible()) {
      await zenBtn.click({ force: true });
      await page.waitForSelector('.xc-immersion-hud', { timeout: 8000 });
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `${ARTIFACT_DIR}/render_live_zen_immersion.png` });
      
      const exitBtn = page.locator("button:has-text('Exit Zen')").first();
      if (await exitBtn.isVisible()) {
        await exitBtn.click({ force: true });
      } else {
        await page.keyboard.press('z');
      }
      await page.locator('.xc-immersion-hud').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(1000);
    } else {
      console.log('Zen button not visible, pressing Z key');
      await page.keyboard.press('z');
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `${ARTIFACT_DIR}/render_live_zen_immersion.png` });
      await page.keyboard.press('z');
      await page.waitForTimeout(1000);
    }
  } catch (err) {
    console.log('Zen error:', err);
  }

  console.log('6. Inside Node Metropolis Tour...');
  try {
    const cityBtn = page.locator("button[aria-label*='Zoom inside node'], button.xc-zoom-text:has-text('3D+')").first();
    if (await cityBtn.isVisible()) {
      await cityBtn.click({ force: true });
      await page.waitForSelector('.xc-city-hud', { timeout: 8000 });
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `${ARTIFACT_DIR}/render_live_city_reentry.png` });
      
      const exitCity = page.locator("button:has-text('Ascend to Orbit')").first();
      if (await exitCity.isVisible()) {
        await exitCity.click({ force: true });
        await page.waitForTimeout(1000);
      }
    } else {
      console.log('City button not directly visible; attempting double-click in center canvas');
      await page.mouse.dblclick(800, 480);
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `${ARTIFACT_DIR}/render_live_city_reentry.png` });
    }
  } catch (err) {
    console.log('City reentry error:', err);
  }

  await browser.close();
  console.log('UI Feature Tour Finished!');
}

run().catch(console.error);
