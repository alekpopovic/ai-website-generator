import { TestBed } from '@angular/core/testing';
import type { SectionPatternResponse } from '@platform/api-client';

import { AnalysisReviewApiService } from '../../core/analysis/analysis-review-api.service';
import { NotificationService } from '../../core/notifications/notification.service';
import { ScanReviewApiService } from '../../core/scans/scan-review-api.service';
import { DatasetPatternCuratorComponent } from './dataset-pattern-curator.component';

const PATTERN = {
  id: '10000000-0000-4000-8000-000000000001',
  version: 1,
  section_type: 'hero',
  category: 'homepage',
  layout: 'split',
  language: 'en',
  confidence: 0.91,
  approval_state: 'needs_review',
  provenance_state: 'authorized',
  pattern: { section_type: 'hero', order: 0, copy_purpose: 'value-proposition', layout: 'split' },
  style_tags: ['minimalist'],
} as unknown as SectionPatternResponse;

describe('DatasetPatternCuratorComponent', () => {
  it('loads server-side facets and performs a bulk review without rendering raw HTML', async () => {
    const api = {
      sectionPatterns: vi.fn().mockResolvedValue({
        items: [PATTERN],
        pagination: { offset: 0, limit: 100, total: 1, has_more: false },
        meta: {},
      }),
      patternFacets: vi.fn().mockResolvedValue({
        total: 1,
        domains: [{ value: 'source.example', count: 1 }],
        categories: [{ value: 'homepage', count: 1 }],
        page_types: [{ value: 'homepage', count: 1 }],
        section_types: [{ value: 'hero', count: 1 }],
        layouts: [{ value: 'split', count: 1 }],
        languages: [{ value: 'en', count: 1 }],
        approvals: [{ value: 'needs_review', count: 1 }],
        provenance: [{ value: 'authorized', count: 1 }],
      }),
      curatePatterns: vi.fn().mockResolvedValue([{ ...PATTERN, approval_state: 'approved' }]),
    };
    const notifications = { success: vi.fn(), error: vi.fn() };
    await TestBed.configureTestingModule({
      imports: [DatasetPatternCuratorComponent],
      providers: [
        { provide: AnalysisReviewApiService, useValue: api },
        { provide: ScanReviewApiService, useValue: { screenshot: vi.fn() } },
        { provide: NotificationService, useValue: notifications },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(DatasetPatternCuratorComponent);
    fixture.componentRef.setInput('projectId', 'project-id');
    fixture.detectChanges();
    await vi.waitFor(() => {
      expect(fixture.componentInstance.loading()).toBe(false);
    });
    fixture.detectChanges();

    fixture.componentInstance.toggle(PATTERN.id);
    await fixture.componentInstance.bulkCurate('approved');
    fixture.detectChanges();

    expect(api.patternFacets).toHaveBeenCalledOnce();
    expect(api.curatePatterns).toHaveBeenCalledWith('project-id', [PATTERN], 'approved', null);
    expect((fixture.nativeElement as HTMLElement).querySelector('iframe')).toBeNull();
    expect((fixture.nativeElement as HTMLElement).textContent).not.toContain('<html');
  });
});
