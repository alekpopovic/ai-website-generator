import { expect, test } from '@playwright/test';
import type {
  AccessTokenResponse,
  ApiResponseVersionInfo,
  DependencyHealthResponse,
  PageResponseProjectResponse,
  ProblemDetail,
  ProjectResponse,
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

const PROJECT = {
  id: '8d922dd8-530f-4270-a5c2-d2f783614834',
  owner_id: USER.id,
  name: 'Portfolio workspace',
  slug: 'portfolio-workspace',
  description: 'A project used by the UI test.',
  default_language: 'en',
  default_industry: 'Creative services',
  status: 'draft',
  settings: {},
  created_at: '2026-07-27T10:00:00Z',
  updated_at: '2026-07-27T10:00:00Z',
  version: 1,
} satisfies ProjectResponse;

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

async function fakeProjects(
  page: import('@playwright/test').Page,
  projects: readonly ProjectResponse[],
): Promise<void> {
  await page.route('http://127.0.0.1:8000/api/v1/projects**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/projects') {
      const body = {
        items: [...projects],
        pagination: {
          offset: 0,
          limit: 12,
          total: projects.length,
          has_more: false,
        },
        meta: { request_id: 'e2e-projects' },
      } satisfies PageResponseProjectResponse;
      await route.fulfill({ status: 200, json: body });
      return;
    }
    const project = projects.find((item) => url.pathname === `/api/v1/projects/${item.id}`);
    await route.fulfill(
      project === undefined
        ? { status: 404, json: { ...UNAUTHENTICATED, status: 404, title: 'Not Found' } }
        : { status: 200, json: project },
    );
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
  await fakeProjects(page, []);
  await page.goto('/dashboard');
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  const projectsLink = page.getByRole('link', { name: 'Projects' });
  if (!(await projectsLink.isVisible())) {
    await page.getByRole('button', { name: 'Toggle navigation' }).click();
  }
  await projectsLink.click();

  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await expect(page.getByText('No projects found')).toBeVisible();
});

test('project list opens a detail shell with all workspace tabs', async ({ page }) => {
  await fakeSession(page, true);
  await fakeProjects(page, [PROJECT]);
  await page.goto('/projects');

  await page.getByRole('link', { name: PROJECT.name }).click();

  await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT.id}/generated-sites$`));
  await expect(page.getByRole('heading', { name: PROJECT.name })).toBeVisible();
  const projectSections = page.getByLabel('Project sections');
  for (const tab of ['Generated sites', 'Scans', 'Datasets', 'Assets', 'Settings']) {
    await expect(projectSections.getByRole('link', { name: tab, exact: true })).toBeVisible();
  }
});

test('project creation form exposes workspace defaults without fake data', async ({ page }) => {
  await fakeSession(page, true);
  await page.goto('/projects/new');

  await expect(page.getByRole('heading', { name: 'Create project' })).toBeVisible();
  await expect(page.getByLabel('Name')).toBeVisible();
  await expect(page.getByLabel('Default language')).toHaveValue('en');
  await expect(page.getByLabel('Settings JSON')).toHaveValue('{}');
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

test('scan review lists campaigns and never renders captured HTML', async ({ page }) => {
  await fakeSession(page, true);
  await fakeProjects(page, [PROJECT]);
  const campaignId = '01941f10-7b2c-7000-8000-000000000101';
  const pageId = '01941f10-7b2c-7000-8000-000000000102';
  const targetId = '01941f10-7b2c-7000-8000-000000000103';
  const now = '2026-07-28T09:00:00Z';
  const campaign = {
    id: campaignId,
    project_id: PROJECT.id,
    name: 'Fixture site review',
    authorization_attested_at: now,
    respect_robots_txt: true,
    status: 'succeeded',
    workflow_id: null,
    workflow_run_id: null,
    workflow_attempt: 1,
    started_at: now,
    completed_at: now,
    created_at: now,
    updated_at: now,
    version: 2,
  };
  const scanPage = {
    id: pageId,
    campaign_id: campaignId,
    target_id: targetId,
    parent_page_id: null,
    crawl_policy_record_id: null,
    url: 'https://fixture.example/pricing',
    normalized_url: 'https://fixture.example/pricing',
    final_url: 'https://fixture.example/pricing',
    declared_canonical_url: null,
    source_domain: 'fixture.example',
    depth: 1,
    status: 'fetched',
    robots_allowed: true,
    crawl_decision_code: 'allowed',
    crawl_policy_provenance: {},
    http_status: 200,
    content_type: 'text/html',
    content_sha256: null,
    title: 'Pricing',
    meta_description: 'Fixture pricing page',
    language: 'en',
    hreflang_links: [],
    last_modified_at: null,
    content_length: 1200,
    discovery_source: 'HTML link',
    parent_url: null,
    fingerprint_algorithm: 'deterministic',
    fingerprint_version: 1,
    normalized_url_sha256: null,
    visible_text_sha256: null,
    dom_structure_sha256: null,
    heading_sequence_sha256: null,
    link_structure_sha256: null,
    semantic_simhash: null,
    dom_template_sha256: null,
    normalized_content_sha256: null,
    normalized_text_length: 500,
    exact_duplicate_of_id: null,
    near_duplicate_of_id: null,
    template_representative_id: null,
    exact_group_key: null,
    near_group_key: null,
    template_group_key: 'pricing-template',
    fingerprinted_at: now,
    page_type: 'pricing',
    page_type_score: 0.98,
    classification_features: {},
    classification_explanation: ['Path contains pricing'],
    classifier: 'rules',
    classifier_version: 1,
    classified_at: now,
    representative_selected: true,
    representative_rank: 1,
    representative_score: 9.5,
    selection_explanation: ['Important page type'],
    selector: 'rules',
    selector_version: 1,
    manual_selection: 'automatic',
    manual_selection_reason: null,
    manual_selected_by_user_id: null,
    manual_selected_at: null,
    discovered_at: now,
    fetched_at: now,
    created_at: now,
    updated_at: now,
    version: 1,
    page_scans: [],
  };
  await page.route(
    `http://127.0.0.1:8000/api/v1/projects/${PROJECT.id}/scan-campaigns**`,
    async (route) => {
      const path = new URL(route.request().url()).pathname;
      const pageResponse = (items: unknown[]) => ({
        items,
        pagination: { offset: 0, limit: 20, total: items.length, has_more: false },
        meta: { request_id: 'scan-e2e' },
      });
      if (path.endsWith(`/pages/${pageId}`)) {
        await route.fulfill({
          status: 200,
          json: { page: scanPage, page_scans: [], failures: [], artifacts: [] },
        });
      } else if (path.endsWith('/pages')) {
        await route.fulfill({ status: 200, json: pageResponse([scanPage]) });
      } else if (path.endsWith(`/${campaignId}`)) {
        await route.fulfill({ status: 200, json: campaign });
      } else {
        await route.fulfill({ status: 200, json: pageResponse([campaign]) });
      }
    },
  );

  await page.goto(`/projects/${PROJECT.id}/scans`);
  await expect(page.getByRole('heading', { name: 'Scan campaigns' })).toBeVisible();
  await page.getByRole('link', { name: campaign.name }).click();
  await page.getByRole('link', { name: 'Pages', exact: true }).click();
  await page.getByRole('link', { name: 'Pricing' }).click();
  await expect(page.getByRole('heading', { name: 'Pricing' })).toBeVisible();
  await expect(page.locator('iframe')).toHaveCount(0);
  await expect(page.locator('[innerhtml]')).toHaveCount(0);
  await expect(page.getByText('Artifact manifest')).toBeVisible();
});
