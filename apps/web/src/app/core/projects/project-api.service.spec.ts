import { TestBed } from '@angular/core/testing';
import { Projects, type ProjectResponse } from '@platform/api-client';

import { ProjectApiService } from './project-api.service';

const PROJECT = {
  id: '8d922dd8-530f-4270-a5c2-d2f783614834',
  owner_id: 'e0db125d-a7fe-4112-8550-a35ef40d18ce',
  name: 'Test project',
  slug: 'test-project',
  description: null,
  default_language: 'en',
  default_industry: null,
  status: 'draft',
  settings: {},
  created_at: '2026-07-27T10:00:00Z',
  updated_at: '2026-07-27T10:00:00Z',
  version: 1,
} satisfies ProjectResponse;

describe('ProjectApiService', () => {
  it('returns generated project page contracts without duplicating interfaces', async () => {
    const api = {
      listProjects: vi.fn(() =>
        Promise.resolve({
          data: {
            items: [PROJECT],
            pagination: { offset: 0, limit: 20, total: 1, has_more: false },
            meta: {},
          },
        }),
      ),
    };
    TestBed.configureTestingModule({
      providers: [ProjectApiService, { provide: Projects, useValue: api }],
    });

    const page = await TestBed.inject(ProjectApiService).list({ limit: 20 });

    expect(page.items).toEqual([PROJECT]);
    expect(api.listProjects).toHaveBeenCalledWith({ query: { limit: 20 } });
  });
});
