import { expect, test } from '@playwright/test';

const PROJECT_ID = '8d922dd8-530f-4270-a5c2-d2f783614834';
const DATASET_ID = '10000000-0000-4000-8000-000000000001';
const VERSION_ID = '20000000-0000-4000-8000-000000000002';
const PATTERN_ID = '30000000-0000-4000-8000-000000000003';
const USER = {
  id: '21d53af6-b752-47b5-b5ce-6d08eb082a33',
  email: 'curator@example.test',
  display_name: 'Curator',
  email_verified: true,
  created_at: '2026-07-29T08:00:00Z',
};
const PROJECT = {
  id: PROJECT_ID,
  owner_id: USER.id,
  name: 'Curation workspace',
  slug: 'curation-workspace',
  description: null,
  default_language: 'en',
  default_industry: null,
  status: 'draft',
  settings: {},
  created_at: '2026-07-29T08:00:00Z',
  updated_at: '2026-07-29T08:00:00Z',
  version: 1,
};
const POLICY = {
  source_campaign_filters: [],
  category_filters: [],
  language_filters: [],
  item_types: ['section_pattern'],
  minimum_confidence: 0.7,
  require_approved: true,
  provenance_requirements: ['authorized'],
};
const DATASET = {
  ...POLICY,
  id: DATASET_ID,
  project_id: PROJECT_ID,
  name: 'Layout corpus',
  description: 'Curated layouts',
  purpose: 'Layout retrieval',
  status: 'active',
  created_by_user_id: USER.id,
  created_at: '2026-07-29T08:00:00Z',
  updated_at: '2026-07-29T08:00:00Z',
  version: 1,
};
const VERSION = {
  id: VERSION_ID,
  dataset_id: DATASET_ID,
  status: 'draft',
  version_number: 1,
  selection_config: POLICY,
  selection_manifest: {},
  manifest_sha256: null,
  schema_version: 1,
  embedding_version: null,
  analyzer_versions: [],
  statistics: {},
  created_by_user_id: USER.id,
  sealed_by_user_id: null,
  sealed_at: null,
  created_at: '2026-07-29T08:00:00Z',
  updated_at: '2026-07-29T08:00:00Z',
  version: 1,
};
const PATTERN = {
  id: PATTERN_ID,
  project_id: PROJECT_ID,
  campaign_id: '40000000-0000-4000-8000-000000000004',
  source_website_id: '50000000-0000-4000-8000-000000000005',
  source_page_id: '60000000-0000-4000-8000-000000000006',
  analysis_run_id: '70000000-0000-4000-8000-000000000007',
  page_profile_id: '80000000-0000-4000-8000-000000000008',
  duplicate_of_id: null,
  pattern: {
    section_type: 'hero',
    order: 0,
    copy_purpose: 'value-proposition',
    layout: 'split',
    components: [
      {
        component_name: 'heading',
        order: 0,
        copy_purpose: 'value-proposition',
        repeat_count: 1,
        layout: 'block',
      },
    ],
  },
  section_order: 0,
  section_type: 'hero',
  layout: 'split',
  style_tags: ['minimalist'],
  category: 'homepage',
  language: 'en',
  confidence: 0.91,
  schema_version: 1,
  analyzer_version: 'analyzer-v1',
  model_digest: 'a'.repeat(64),
  approval_state: 'needs_review',
  provenance_state: 'authorized',
  retrieval_document: 'section=hero layout=split',
  pattern_hash: 'b'.repeat(64),
  retrieval_expires_at: null,
  retrieval_removed_at: null,
  legally_suppressed_at: null,
  review_note: null,
  reviewed_at: null,
  created_at: '2026-07-29T08:00:00Z',
  version: 1,
};

test.beforeEach(async ({ page }) => {
  await page.route('http://127.0.0.1:8000/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path.endsWith('/auth/refresh')) {
      await route.fulfill({
        status: 200,
        json: { access_token: 'e2e-token', expires_in: 300, token_type: 'bearer', user: USER },
      });
      return;
    }
    if (path.endsWith('/auth/me')) {
      await route.fulfill({ status: 200, json: USER });
      return;
    }
    if (path === `/api/v1/projects/${PROJECT_ID}`) {
      await route.fulfill({ status: 200, json: PROJECT });
      return;
    }
    await route.fallback();
  });
});

test('dataset creation wizard creates the definition and first draft', async ({ page }) => {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.stack ?? error.message));
  page.on('console', (entry) => {
    if (entry.type() === 'error') consoleErrors.push(entry.text());
  });
  let created = false;
  await page.route(
    `http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/datasets**`,
    async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (request.method() === 'POST' && path.endsWith('/datasets')) {
        created = true;
        await route.fulfill({ status: 201, json: DATASET });
        return;
      }
      if (request.method() === 'POST' && path.endsWith(`/datasets/${DATASET_ID}/versions`)) {
        await route.fulfill({ status: 201, json: VERSION });
        return;
      }
      await route.fallback();
    },
  );
  await page.goto(`/projects/${PROJECT_ID}/datasets/new`);
  await page.waitForTimeout(500);
  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);

  await page.getByLabel('Name').fill('Layout corpus');
  await page.getByLabel('Purpose').fill('Layout retrieval');
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByLabel('Categories').fill('homepage, pricing');
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByRole('button', { name: 'Create dataset and draft' }).click();

  await expect.poll(() => created).toBe(true);
  await expect(page).toHaveURL(new RegExp(`/datasets/${DATASET_ID}/versions/${VERSION_ID}$`));
});

test('draft curation uses server facets, bulk actions, warnings, and build progress', async ({
  page,
}) => {
  let approval = 'needs_review';
  let buildPoll = 0;
  const build = (status: string, stage: string) => ({
    id: '90000000-0000-4000-8000-000000000009',
    project_id: PROJECT_ID,
    dataset_id: DATASET_ID,
    dataset_version_id: VERSION_ID,
    requested_by_user_id: USER.id,
    status,
    stage,
    idempotency_key: 'e2e-build',
    quality_policy: {
      max_domain_share: 0.6,
      minimum_category_count: 2,
      max_repeated_template_share: 0.25,
      required_section_types: [],
      maximum_serialized_text_chars: 20000,
    },
    enqueue_missing_embeddings: false,
    excluded_counts: {},
    workflow_id: 'dataset-build-e2e',
    workflow_run_id: null,
    workflow_attempt: 1,
    failure_code: null,
    started_at: '2026-07-29T08:00:00Z',
    completed_at: status === 'succeeded' ? '2026-07-29T08:01:00Z' : null,
    cancelled_at: null,
    created_at: '2026-07-29T08:00:00Z',
    updated_at: '2026-07-29T08:00:00Z',
    version: 1,
  });
  await page.route(`http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (
      path.endsWith(`/datasets/${DATASET_ID}/versions/${VERSION_ID}`) &&
      request.method() === 'GET'
    ) {
      await route.fulfill({
        status: 200,
        json: {
          dataset: DATASET,
          version: VERSION,
          quality_report: {
            id: 'a0000000-0000-4000-8000-000000000010',
            dataset_version_id: VERSION_ID,
            status: 'failed',
            item_count: 12,
            statistics: {
              item_count: 12,
              source_domain_count: 3,
              largest_domain_share: 0.75,
              source_domain_leakage_count: 0,
              excluded: { unauthorized_provenance: 2 },
              splits: { train: 8, validation: 2, test: 2 },
              categories: { homepage: 8, pricing: 4 },
              languages: { en: 12 },
              section_types: { hero: 7, footer: 5 },
              layouts: { split: 12 },
              styles: { minimalist: 12 },
            },
            findings: [
              {
                code: 'excessive_domain_dependence',
                message: 'One source domain exceeds the configured share.',
              },
            ],
            report_version: 1,
            created_at: '2026-07-29T08:00:00Z',
          },
        },
      });
      return;
    }
    if (path.endsWith(`/datasets/${DATASET_ID}/versions/${VERSION_ID}/items`)) {
      await route.fulfill({
        status: 200,
        json: {
          items: [],
          pagination: { offset: 0, limit: 100, total: 0, has_more: false },
          meta: {},
        },
      });
      return;
    }
    if (path.endsWith('/analysis/section-patterns/facets')) {
      await route.fulfill({
        status: 200,
        json: {
          total: 1,
          domains: [{ value: 'source.example', count: 1 }],
          categories: [{ value: 'homepage', count: 1 }],
          page_types: [{ value: 'homepage', count: 1 }],
          section_types: [{ value: 'hero', count: 1 }],
          layouts: [{ value: 'split', count: 1 }],
          languages: [{ value: 'en', count: 1 }],
          approvals: [{ value: approval, count: 1 }],
          provenance: [{ value: 'authorized', count: 1 }],
        },
      });
      return;
    }
    if (path.endsWith('/analysis/section-patterns') && request.method() === 'GET') {
      await route.fulfill({
        status: 200,
        json: {
          items: [{ ...PATTERN, approval_state: approval }],
          pagination: { offset: 0, limit: 100, total: 1, has_more: false },
          meta: {},
        },
      });
      return;
    }
    if (path.endsWith('/analysis/section-patterns/bulk-curation')) {
      approval = 'approved';
      await route.fulfill({
        status: 200,
        json: [{ ...PATTERN, approval_state: approval, version: 2 }],
      });
      return;
    }
    if (path.endsWith(`/analysis/section-patterns/${PATTERN_ID}/detail`)) {
      await route.fulfill({
        status: 200,
        json: {
          pattern: { ...PATTERN, approval_state: approval },
          design_tokens: null,
          source: {
            domain: 'source.example',
            url: 'https://source.example/',
            final_url: null,
            title: 'Source',
            http_status: 200,
            content_type: 'text/html',
            scanned_at: '2026-07-29T08:00:00Z',
          },
          analysis: {
            prompt_version: 'v1',
            analyzer_version: 'analyzer-v1',
            strategy: 'dspy',
            model_name: 'private-model',
            model_digest: 'a'.repeat(64),
            schema_version: 1,
            latency_ms: 10,
            attempts: 1,
            used_fallback: false,
          },
          embedding: {
            status: 'indexed',
            model: 'embed-v1',
            collection: 'patterns',
            indexed_at: '2026-07-29T08:00:00Z',
            error_code: null,
          },
          screenshot: null,
        },
      });
      return;
    }
    if (
      path.endsWith(`/datasets/${DATASET_ID}/versions/${VERSION_ID}/builds`) &&
      request.method() === 'POST'
    ) {
      await route.fulfill({ status: 202, json: build('running', 'compute-distributions') });
      return;
    }
    if (
      path.includes('/builds/90000000-0000-4000-8000-000000000009') &&
      request.method() === 'GET'
    ) {
      buildPoll += 1;
      await route.fulfill({
        status: 200,
        json: build(
          buildPoll > 1 ? 'succeeded' : 'running',
          buildPoll > 1 ? 'complete' : 'materialize-version-manifest',
        ),
      });
      return;
    }
    await route.fallback();
  });

  await page.goto(`/projects/${PROJECT_ID}/datasets/${DATASET_ID}/versions/${VERSION_ID}`);
  await expect(page.getByRole('heading', { name: 'Pattern curation' })).toBeVisible();
  await expect(page.getByLabel('Domain')).toBeVisible();
  await expect(page.getByText('Source concentration warning.')).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Train, validation, and test splits' }),
  ).toBeVisible();
  await page.getByLabel('Select hero pattern').check();
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect.poll(() => approval).toBe('approved');
  await page.getByRole('button', { name: 'Build and seal version' }).click();
  await expect(page.getByRole('heading', { name: 'Build progress' })).toBeVisible();
  await expect.poll(() => buildPoll, { timeout: 6000 }).toBeGreaterThan(1);
});
