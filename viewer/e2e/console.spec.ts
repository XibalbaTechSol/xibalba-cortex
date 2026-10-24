// The console (the default UI since the redesign) against a mocked local_api. No backend runs:
// every /api/* request is answered here, and every one is recorded so a test can assert which
// workspace the console actually asked for.
import { test, expect, type Page } from '@playwright/test';

const STORE = 'store-0123456789abcdef';
const workspace = (agent_id: string, extra: Record<string, unknown> = {}) => ({
  agent_id, store_id: STORE, profile_id: 'default', store_access: 'writable', writable: true,
  memories: 0, memories_counted: false, sessions: 0, sessions_counted: false, ...extra,
});
const memory = {
  id: 'm-1', content: 'Relay retries three times.', content_hash: 'sha256:00', status: 'confirmed',
  created_at: '2026-10-24 10:00:00', source: { kind: 'direct_user', agent_id: 'xibalba.agent' },
  evidence_class: 'observed_event', quarantine_reasons: [], supersedes_id: null,
};

function body(path: string): unknown | undefined {
  switch (path) {
    case '/api/auth/me': return { account: { id: 'a-1', email: 'operator@example.test', display_name: 'Operator', role: 'operator', profile_id: 'default' } };
    case '/api/auth/csrf': return { csrf_token: 'csrf' };
    case '/api/agents': return {
      primary_profile_id: 'default', oracle_reachable: false,
      // a device paired before its agent wrote anything is listed first, counted as empty
      agents: [workspace('claude', { device_id: 'workstation-1', memories_counted: true }), workspace('xibalba.agent')],
    };
    case '/api/graph': return { nodes: [{ id: 'memory:m-1', type: 'memory', label: memory.content, status: 'confirmed' }], edges: [] };
    case '/api/memories': return { memories: [memory], total: 1 };
    case '/api/sessions': return [];
    case '/api/sessions/page': return { sessions: [], total: 0 };
    case '/api/stats': return { memories: 1, entities: 0, relations: 0, sessions: 0, embedded_memories: 1 };
    case '/api/status': return {
      schema_version: 16, profile_id: 'default', journal_mode: 'wal', foreign_keys: true, fts5: true,
      integrity_check: 'ok', identity_mode: 'pseudonymous', db_path: 'graph-memory.sqlite3', memory_count: 1,
      backup_ready: true, backup_method: 'sqlite online backup',
    };
    default: return undefined; // unmocked: answered 404, as a backend without the route would
  }
}

async function signedInConsole(page: Page): Promise<string[]> {
  const scoped: string[] = [];
  await page.addInitScript(() => sessionStorage.setItem('xibalba-cortex.signed-in', '1'));
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.has('agent_id')) scoped.push(`${url.pathname}?agent_id=${url.searchParams.get('agent_id')}`);
    const payload = body(url.pathname);
    if (payload === undefined) return route.fulfill({ status: 404, contentType: 'application/json', body: '{"error":"not found"}' });
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
  });
  await page.goto('/');
  // the rail on a desktop, the tab bar on a phone: both carry Graph
  await expect(page.getByRole('button', { name: 'Graph' }).first()).toBeVisible();
  return scoped;
}

test.describe('Console', () => {
  test('signed out, it opens on sign-in with both account tabs', async ({ page }) => {
    await page.route('**/api/**', (route) => route.fulfill({ status: 401, contentType: 'application/json', body: '{"error":"authentication required"}' }));
    await page.goto('/');
    await expect(page.getByRole('tab', { name: 'Sign in' })).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Create account' })).toBeVisible();
    await expect(page.locator('input[type=email]')).toBeVisible();
  });

  test('opens the populated workspace, not a paired one with no memories', async ({ page }) => {
    const scoped = await signedInConsole(page);
    await expect(page.locator('.xc-conn')).toHaveAttribute('data-state', 'ready');
    await expect.poll(() => scoped.length).toBeGreaterThan(0);
    expect(scoped.every((r) => r.endsWith('agent_id=xibalba.agent'))).toBe(true);
    expect(new URL(page.url()).searchParams.get('agent_id')).toBe('xibalba.agent');
  });

  test('every rail destination renders without a page error', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await signedInConsole(page);
    for (const name of ['Timeline', 'Memories', 'Entities', 'Sessions', 'Review', 'Integrity', 'Operations', 'Agents', 'Settings', 'Graph']) {
      await page.locator('.xc-nav-btn').filter({ hasText: new RegExp(`^${name}`) }).first().click();
      await page.waitForTimeout(300);
      expect(errors, `after opening ${name}`).toEqual([]);
      await expect(page.locator('.xc-nav-btn').first(), `shell still mounted after ${name}`).toBeVisible();
      await page.keyboard.press('Escape'); // Review and Integrity open as dialogs
    }
  });

  test('at phone width the console does not scroll sideways', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await signedInConsole(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
});
