import { expect, test } from '@playwright/test';

test.describe('Replay page', () => {
  test('renders replay command center basics', async ({ page }) => {
    await page.goto('/replay');
    await expect(page.getByText('Historical Replay Command Center')).toBeVisible();
    await expect(page.getByText('Replay how the anomaly stack behaves before an operator ever clicks refresh.')).toBeVisible();
    await expect(page.locator('input[type="range"]')).toBeVisible();
    await expect(page.getByText('Incident Library')).toBeVisible();
  });
});
