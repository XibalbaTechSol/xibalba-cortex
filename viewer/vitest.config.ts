import { defineConfig } from 'vitest/config'

// Unit tests cover the pure console model (src/console/model.ts and friends). They run in plain
// node: nothing under test touches the DOM, and the Playwright smoke test in e2e/ owns the browser.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
