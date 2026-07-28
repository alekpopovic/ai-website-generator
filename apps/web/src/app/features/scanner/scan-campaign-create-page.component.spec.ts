import { provideRouter } from '@angular/router';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';

import { ScanReviewApiService } from '../../core/scans/scan-review-api.service';
import { ScanCampaignCreatePageComponent } from './scan-campaign-create-page.component';

describe('ScanCampaignCreatePageComponent', () => {
  it('uses bounded defaults and requires an authorization attestation', async () => {
    await TestBed.configureTestingModule({
      imports: [ScanCampaignCreatePageComponent],
      providers: [
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: new Map([['projectId', 'project-id']]) } },
        },
        { provide: ScanReviewApiService, useValue: {} },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(ScanCampaignCreatePageComponent);
    fixture.detectChanges();
    const component = fixture.componentInstance;

    expect(component.form.controls.maxPages.value).toBe(100);
    expect(component.form.controls.maxVisualPages.value).toBe(20);
    expect(component.form.controls.authorized.invalid).toBe(true);
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('iframe')).toBeNull();
  });
});
