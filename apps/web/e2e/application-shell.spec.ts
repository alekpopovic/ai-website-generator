import { expect, test } from '@playwright/test';
import type {
  AccessTokenResponse,
  ApiResponseVersionInfo,
  DependencyHealthResponse,
  ProblemDetail,
  UserResponse,
} from '@platform/api-client';

const USER = {
  id: '21d53af6-b752-47b5-b5ce-6d08eb082a33',
  email: 'developer@example.test',
  display_name: 'Developer',
  email_verified: true,
  created_at: '2026-07-27T10:00:00Z',
} satisfies UserResponse;

const SESSION = {
  access_token: 'e2e-memory-access-token',
  expires_in: 300,
  token_type: 'bearer',
  user: USER,
} satisfies AccessTokenResponse;

const UNAUTHENTICATED = {
  title: 'Unauthorized',
  status: 401,
  code: 'authentication_required',
  request_id: 'e2e-auth',
} satisfies ProblemDetail;

async function fakeSession(
  page: import('@playwright/test').Page,
  authenticated: boolean,
): Promise<void> {
  await page.route('http://127.0.0.1:8000/api/v1/auth/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/refresh')) {
      await route.fulfill(
        authenticated
          ? { status: 200, json: SESSION }
          : { status: 401, contentType: 'application/problem+json', json: UNAUTHENTICATED },
      );
      return;
    }
    if (path.endsWith('/me')) {
      await route.fulfill({ status: 200, json: USER });
      return;
    }
    await route.fallback();
  });
}

test('public login shell is accessible by role', async ({ page }) => {
  await fakeSession(page, false);
  await page.goto('/login');

  await expect(page).toHaveTitle('Sign in | Website Generator');
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  await expect(page.getByLabel('Email address')).toBeVisible();
  await expect(page.getByLabel('Password')).toBeVisible();
});

test('registration form exposes accessible first-party account fields', async ({ page }) => {
  await fakeSession(page, false);
  await page.goto('/register');

  await expect(page).toHaveTitle('Create account | Website Generator');
  await expect(page.getByRole('heading', { name: 'Create account' })).toBeVisible();
  await expect(page.getByLabel('Display name')).toBeVisible();
  await expect(page.getByLabel('Email address')).toBeVisible();
  await expect(page.getByLabel('Password', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Confirm password')).toBeVisible();
});

test('authenticated shell provides lazy feature navigation', async ({ page }) => {
  await fakeSession(page, true);
  await page.goto('/dashboard');
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  const projectsLink = page.getByRole('link', { name: 'Projects' });
  if (!(await projectsLink.isVisible())) {
    await page.getByRole('button', { name: 'Toggle navigation' }).click();
  }
  await projectsLink.click();

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
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/api/v1/auth/refresh')) {
      await route.fulfill({ status: 200, headers, json: SESSION });
      return;
    }
    if (path.endsWith('/api/v1/auth/me')) {
      await route.fulfill({ status: 200, headers, json: USER });
      return;
    }
    const body = path.endsWith('/api/v1/version') ? version : dependencyHealth;
    await route.fulfill({ status: 200, headers, json: body });
  });

  await page.goto('/diagnostics');

  await expect(page.getByRole('heading', { name: 'API diagnostics' })).toBeVisible();
  await expect(page.getByText('v1')).toBeVisible();
  await expect(page.getByText('database')).toBeVisible();
  await expect(page.getByText('available')).toBeVisible();
});
