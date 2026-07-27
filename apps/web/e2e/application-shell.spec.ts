import { expect, test } from '@playwright/test';
import type { ApiResponseVersionInfo, DependencyHealthResponse } from '@platform/api-client';

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

test('developer diagnostics uses generated API contracts with local UI fakes', async ({ page }) => {
  const version = {
    data: { api_version: 'v1', service_version: 'test', environment: 'test' },
    meta: { request_id: 'e2e-version' },
  } satisfies ApiResponseVersionInfo;
  const dependencyHealth = {
    status: 'healthy',
    dependencies: [{ name: 'database', state: 'available', critical: true, latency_ms: 0 }],
  } satisfies DependencyHealthResponse;

  await page.route('http://127.0.0.1:8000/**', async (route) => {
    const headers = {
      'Access-Control-Allow-Credentials': 'true',
      'Access-Control-Allow-Headers': 'Content-Type, X-Request-ID',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Access-Control-Allow-Origin': 'http://127.0.0.1:4200',
    };
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers });
      return;
    }
    const body = route.request().url().endsWith('/api/v1/version') ? version : dependencyHealth;
    await route.fulfill({ status: 200, headers, json: body });
  });

  await page.goto('/diagnostics');

  await expect(page.getByRole('heading', { name: 'API diagnostics' })).toBeVisible();
  await expect(page.getByText('v1')).toBeVisible();
  await expect(page.getByText('database')).toBeVisible();
  await expect(page.getByText('available')).toBeVisible();
});
