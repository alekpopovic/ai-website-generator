import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { PlatformApiConfiguration, type ScanTargetImportResponse } from '@platform/api-client';

import { ScanTargetImportApiService } from './scan-target-import-api.service';

describe('ScanTargetImportApiService', () => {
  let service: ScanTargetImportApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    TestBed.inject(PlatformApiConfiguration).configure({ baseUrl: 'https://api.example.test' });
    service = TestBed.inject(ScanTargetImportApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  it('uploads a raw CSV body with typed import options and progress enabled', () => {
    const body = new File(['domain,category\nexample.com,agency\n'], 'targets.csv', {
      type: 'text/csv',
    });
    const responses: ScanTargetImportResponse[] = [];

    service
      .upload({
        projectId: 'project-id',
        campaignId: 'campaign-id',
        body,
        sourceType: 'csv',
        filename: body.name,
        dryRun: true,
        authorizationAttested: true,
      })
      .subscribe((event) => {
        if ('body' in event && event.body !== null) responses.push(event.body);
      });

    const request = http.expectOne(
      'https://api.example.test/api/v1/projects/project-id/scan-campaigns/campaign-id/target-imports?source_type=csv&authorization_attested=true&dry_run=true&filename=targets.csv',
    );
    expect(request.request.body).toBe(body);
    expect(request.request.reportUploadProgress).toBe(true);
    expect(request.request.headers.get('Content-Type')).toBe('text/csv');
    request.flush(importSummary);
    expect(responses[0]?.accepted_count).toBe(1);
  });
});

const importSummary: ScanTargetImportResponse = {
  id: '01941f10-7b2c-7000-8000-000000000001',
  campaign_id: '01941f10-7b2c-7000-8000-000000000002',
  source_type: 'csv',
  filename: 'targets.csv',
  media_type: 'text/csv',
  dry_run: true,
  authorization_attested_at: '2026-07-27T16:00:00Z',
  allow_ip_literals: false,
  status: 'completed',
  total_rows: 1,
  processed_rows: 1,
  accepted_count: 1,
  duplicate_count: 0,
  invalid_count: 0,
  blocked_count: 0,
  already_present_count: 0,
  committed_count: 0,
  committed_at: null,
  created_at: '2026-07-27T16:00:00Z',
  updated_at: '2026-07-27T16:00:00Z',
  version: 1,
};
