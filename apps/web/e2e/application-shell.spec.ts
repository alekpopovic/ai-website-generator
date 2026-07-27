import { expect, test } from '@playwright/test';

test('public login shell is accessible by role', async ({ page }) => {
  await page.goto('/login');

  await expect(page).toHaveTitle('Sign in | Website Generator');
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  await expect(page.getByLabel('Email address')).toBeVisible();
  await expect(page.getByLabel('Password')).toBeVisible();
});

test('authenticated shell provides lazy feature navigation', async ({ page }) => {
  await page.goto('/dashboard');
  await page.getByRole('link', { name: 'Projects' }).click();

  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible();
  await expect(page.getByText('Nothing here yet')).toBeVisible();
});
