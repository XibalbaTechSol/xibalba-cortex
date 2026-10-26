// Headless browser validation of the Cortex console against a real API and a real fixture profile.
//
//   npm run test:e2e                     # everything, headless
//   npx playwright test -g "drawers"     # a subset
//
// What it starts (sequentially, in this order):
//   0. an anchor-service stand-in (e2e/anchor-stub.mjs) on :8431;
//   1. a scratch Cortex profile seeded by scripts/dev_seed_console.py (real GraphStore writes, then
//      backdated timestamps) and `xibalba_cortex.local_api` serving it on :8420;
//   2. the Vite dev server on :5190, whose proxy injects a local-development operator token, so the
//      console boots signed in exactly as `npm run dev` does.
// Nothing here touches ~/.hermes/xibalba-cortex: the profile lives in E2E_CORTEX_HOME (default: a
// fresh folder under the OS temp dir) and the seed script refuses to run against a real profile.
//
// Environment:
//   E2E_PYTHON         command that runs Python with xibalba_cortex importable   (default: "uv run python")
//   E2E_CORTEX_HOME    scratch profile folder                                     (default: <tmp>/cortex-e2e)
//   CHROMIUM_PATH      a Chromium binary to use instead of Playwright's download  (default: Playwright's)
//   CI                 when set, servers are never reused and failures retry once
//
// WebGL: the 3D lens needs it. Headless Chromium has no GPU, so it is launched with SwiftShader
// (software GL via ANGLE): https://github.com/google/swiftshader
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { defineConfig, devices } from '@playwright/test'

const repoRoot = resolve(import.meta.dirname, '..')
const home = process.env.E2E_CORTEX_HOME ?? join(tmpdir(), 'cortex-e2e')
const python = process.env.E2E_PYTHON ?? 'uv run python'
const apiPort = Number(process.env.E2E_API_PORT ?? 28420)
const uiPort = Number(process.env.E2E_UI_PORT ?? 25190)
const anchorPort = Number(process.env.E2E_ANCHOR_PORT ?? 28431)
// Server-side destinations the console's actions use. The browser is never told these; they are the
// server's own configuration, set here for the fixture API only.
const backupDir = join(tmpdir(), 'cortex-e2e-backups')

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  // A few tests write to the fixture (a memory, a device pairing). Each writes something unique and
  // none depends on another's output, but one worker keeps the 3D engine from fighting for the
  // single software-GL context.
  fullyParallel: false,
  /* No failure cap. `maxFailures: 5` on CI hid the true state of the suite three times in one
     sitting: a red run reported 4 timeline failures when there were 6, then concealed the
     projection-dock test, then concealed the design-system sweep entirely. Each "complete"
     failure list was wrong, and each fix round started from a count that was short, so the
     cap cost more wall-clock in re-runs than the early exit ever saved. A red run should
     print everything that is red. */
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${uiPort}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: {
      executablePath: process.env.CHROMIUM_PATH || undefined,
      args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
    },
  },
  projects: [
    { name: 'desktop', testIgnore: /phone\.spec\.ts/, use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    // Phone layout is a different arrangement of the same components (<= 760px), so it has its own spec.
    { name: 'phone', testMatch: /phone\.spec\.ts/, use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 } } },
  ],
  webServer: [
    {
      // stands in for the anchor service, so anchoring a session root works end to end with no outside network
      command: `node e2e/anchor-stub.mjs ${anchorPort}`,
      cwd: import.meta.dirname,
      url: `http://127.0.0.1:${anchorPort}/healthz`,
      timeout: 30_000,
      reuseExistingServer: false,
    },
    {
      // seed, then serve. --reset only deletes the SQLite files the seed itself would create.
      command: `${python} scripts/dev_seed_console.py --home "${home}" --reset --scenario both && exec ${python} -m xibalba_cortex.local_api --home "${home}" --port ${apiPort}`,
      cwd: repoRoot,
      env: { PYTHONPATH: [join(repoRoot, 'src'), process.env.PYTHONPATH].filter(Boolean).join(':'), XIBALBA_BACKUP_DIR: backupDir, XIBALBA_ANCHOR_URL: `http://127.0.0.1:${anchorPort}/anchor` },
      url: `http://127.0.0.1:${apiPort}/healthz`,
      timeout: 180_000,
      reuseExistingServer: false,
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${uiPort} --strictPort`,
      cwd: import.meta.dirname,
      env: { CORTEX_HOME: home, CORTEX_LOCAL_API_URL: `http://127.0.0.1:${apiPort}` },
      url: `http://127.0.0.1:${uiPort}/`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
})
