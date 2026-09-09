import { test, expect } from '@playwright/test';

test.describe('Visual Regression', () => {
  test('Landing page', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible();
    await expect(page.getByRole('heading', { name: /Memory you can/ })).toBeVisible();
    await expect(page.locator('.cortex-mermaid svg')).toHaveCount(2);
    await expect(page.locator('.cortex-footer')).toBeVisible();
    await expect(page).toHaveScreenshot('landing.png', { fullPage: true });
  });

  test('Sign In view', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /sign in|open workspace/i }).first().click();
    await expect(page.locator('.cortex-auth')).toBeVisible();
    await expect(page.locator('.auth-page-footer')).toBeVisible();
    await expect(page).toHaveScreenshot('signin.png');
  });

  test('Landing page at mobile width', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /Memory you can/ })).toBeVisible();
    await expect(page.locator('.cortex-links')).toBeHidden();
    await expect(page.locator('.cortex-footer')).toBeVisible();
    const pageWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(pageWidth).toBe(390);
    await expect(page).toHaveScreenshot('landing-mobile.png', { fullPage: true });
  });
});
