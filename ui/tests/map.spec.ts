import { test, expect } from '@playwright/test';

const TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || process.env.MAPBOX_TOKEN;

test.describe('Map page', () => {
  test.beforeEach(async ({}, testInfo) => {
    if (!TOKEN) {
      testInfo.skip(true, 'NEXT_PUBLIC_MAPBOX_TOKEN missing; skipping UI smoke test');
    }
  });

  test('renders map + control bar basics', async ({ page }) => {
    await page.goto('/map');
    await expect(page.getByText('NYC Subway Anomaly Command Center')).toBeVisible();
    await expect(page.locator('select')).toBeVisible();
    await expect(page.locator('select')).toHaveValue('All');
    const canvas = page.locator('.mapboxgl-canvas');
    await expect(canvas).toBeVisible({ timeout: 10_000 });

    const n = await page.evaluate(async () => {
      const r = await fetch('/api/stops');
      const d = await r.json();
      return Array.isArray(d) ? d.length : 0;
    });
    expect(n).toBeGreaterThan(100);
  });
});
