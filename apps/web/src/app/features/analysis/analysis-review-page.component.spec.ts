import { TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';

import { AnalysisReviewApiService } from '../../core/analysis/analysis-review-api.service';
import { AnalysisReviewPageComponent } from './analysis-review-page.component';

describe('AnalysisReviewPageComponent', () => {
  it('renders source-safe profile and pattern inspection panels without scanned HTML', async () => {
    const api = {
      pageProfiles: vi.fn().mockResolvedValue({
        items: [],
        pagination: { offset: 0, limit: 100, total: 0, has_more: false },
        meta: {},
      }),
      sectionPatterns: vi.fn().mockResolvedValue({
        items: [],
        pagination: { offset: 0, limit: 100, total: 0, has_more: false },
        meta: {},
      }),
    };
    await TestBed.configureTestingModule({
      imports: [AnalysisReviewPageComponent],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: new Map([['projectId', 'project-id']]) } },
        },
        { provide: AnalysisReviewApiService, useValue: api },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(AnalysisReviewPageComponent);
    fixture.detectChanges();
    await vi.waitFor(() => {
      expect(api.pageProfiles).toHaveBeenCalledOnce();
    });
    await vi.waitFor(() => {
      expect(fixture.componentInstance.loading()).toBe(false);
    });
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.textContent).toContain('Current page profiles');
    expect(element.textContent).toContain('Section patterns');
    expect(element.querySelector('iframe')).toBeNull();
    expect(element.querySelector('[innerHTML]')).toBeNull();
  });
});
