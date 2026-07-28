import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import type { ScanCampaignResponse } from '@platform/api-client';

import { ScanReviewApiService } from '../../core/scans/scan-review-api.service';

@Component({
  imports: [RouterLink, RouterLinkActive, RouterOutlet],
  template: `
    <section class="page-stack">
      <header class="page-header">
        <div>
          <p class="eyebrow">Scan campaign</p>
          <h1>{{ campaign()?.name || 'Campaign review' }}</h1>
          <p>Review persisted scan results. Scanned HTML is never rendered in this interface.</p>
        </div>
        @if (campaign(); as item) {
          <span class="status-pill" [attr.data-state]="item.status">{{ item.status }}</span>
        }
      </header>
      <nav class="project-tabs" aria-label="Campaign review sections">
        @for (tab of tabs; track tab.path) {
          <a
            [routerLink]="tab.path"
            routerLinkActive="project-tab-active"
            [routerLinkActiveOptions]="{ exact: true }"
            >{{ tab.label }}</a
          >
        }
      </nav>
      @if (error()) {
        <div class="state-card" role="alert">{{ error() }}</div>
      }
      <router-outlet />
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScanCampaignDetailShellComponent {
  private readonly api = inject(ScanReviewApiService);
  private readonly route = inject(ActivatedRoute);
  readonly campaign = signal<ScanCampaignResponse | null>(null);
  readonly error = signal<string | null>(null);
  readonly tabs = [
    { path: 'overview', label: 'Overview' },
    { path: 'targets', label: 'Targets' },
    { path: 'pages', label: 'Pages' },
    { path: 'failures', label: 'Failures' },
    { path: 'activity', label: 'Activity' },
  ] as const;

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    const projectId = this.route.snapshot.paramMap.get('projectId') ?? '';
    const campaignId = this.route.snapshot.paramMap.get('campaignId') ?? '';
    try {
      this.campaign.set(await this.api.campaign(projectId, campaignId));
    } catch (error: unknown) {
      this.error.set(error instanceof Error ? error.message : 'Campaign could not be loaded.');
    }
  }
}
