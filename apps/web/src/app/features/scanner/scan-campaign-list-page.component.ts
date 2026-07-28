import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import type { ListScanCampaignsData, ScanCampaignResponse } from '@platform/api-client';

import { ScanReviewApiService } from '../../core/scans/scan-review-api.service';
import { EmptyStateComponent } from '../../shared/states/empty-state.component';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

@Component({
  imports: [DatePipe, ReactiveFormsModule, RouterLink, EmptyStateComponent, LoadingStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="campaigns-heading">
      <header class="page-header">
        <div>
          <p class="eyebrow">Scanner</p>
          <h1 id="campaigns-heading">Scan campaigns</h1>
          <p>Review authorized discovery and browser-scan progress for this project.</p>
        </div>
        <a class="primary-button" [routerLink]="['new']">Create campaign</a>
      </header>

      <form class="filter-bar" [formGroup]="filters" (ngSubmit)="applyFilters()">
        <label
          ><span>Search</span><input class="text-input" type="search" formControlName="search"
        /></label>
        <label>
          <span>Status</span>
          <select class="text-input" formControlName="status">
            <option value="">All statuses</option>
            @for (status of statuses; track status) {
              <option [value]="status">{{ status }}</option>
            }
          </select>
        </label>
        <button class="secondary-button" type="submit">Apply filters</button>
      </form>

      @if (loading()) {
        <app-loading-state label="Loading scan campaigns…" />
      } @else if (error()) {
        <div class="state-card" role="alert">{{ error() }}</div>
      } @else if (campaigns().length === 0) {
        <app-empty-state
          heading="No scan campaigns"
          message="Create a campaign to begin an authorized scan."
        />
      } @else {
        <div class="table-scroll">
          <table class="data-table">
            <caption class="visually-hidden">
              Scan campaigns and progress
            </caption>
            <thead>
              <tr>
                <th scope="col">Campaign</th>
                <th scope="col">Status</th>
                <th scope="col">Progress</th>
                <th scope="col">Updated</th>
              </tr>
            </thead>
            <tbody>
              @for (campaign of campaigns(); track campaign.id) {
                <tr>
                  <th scope="row">
                    <a [routerLink]="[campaign.id]">{{ campaign.name }}</a>
                  </th>
                  <td>
                    <span class="status-pill" [attr.data-state]="campaign.status">{{
                      campaign.status
                    }}</span>
                  </td>
                  <td>
                    <progress max="100" [value]="progress(campaign)"></progress>
                    <small>{{ progressLabel(campaign) }}</small>
                  </td>
                  <td>{{ campaign.updated_at | date: 'medium' }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
        <nav class="pagination-controls" aria-label="Campaign pages">
          <button
            class="secondary-button"
            type="button"
            [disabled]="offset() === 0"
            (click)="previous()"
          >
            Previous
          </button>
          <span>{{ offset() + 1 }}–{{ Math.min(offset() + limit, total()) }} of {{ total() }}</span>
          <button
            class="secondary-button"
            type="button"
            [disabled]="offset() + limit >= total()"
            (click)="next()"
          >
            Next
          </button>
        </nav>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScanCampaignListPageComponent {
  private readonly api = inject(ScanReviewApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly formBuilder = inject(FormBuilder);
  readonly Math = Math;
  readonly limit = 20;
  readonly statuses = [
    'draft',
    'queued',
    'running',
    'paused',
    'succeeded',
    'partially_succeeded',
    'failed',
    'cancelled',
  ] as const;
  readonly campaigns = signal<readonly ScanCampaignResponse[]>([]);
  readonly progressByCampaign = signal<
    Readonly<Record<string, { readonly percent: number; readonly label: string }>>
  >({});
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly offset = signal(0);
  readonly total = signal(0);
  readonly filters = this.formBuilder.nonNullable.group({ search: '', status: '' });
  private readonly projectId = this.route.snapshot.paramMap.get('projectId') ?? '';

  constructor() {
    void this.load();
  }

  progress(campaign: ScanCampaignResponse): number {
    return this.progressByCampaign()[campaign.id]?.percent ?? 0;
  }

  progressLabel(campaign: ScanCampaignResponse): string {
    return this.progressByCampaign()[campaign.id]?.label ?? 'No visual scans yet';
  }

  applyFilters(): void {
    this.offset.set(0);
    void this.load();
  }
  previous(): void {
    this.offset.update((value) => Math.max(0, value - this.limit));
    void this.load();
  }
  next(): void {
    this.offset.update((value) => value + this.limit);
    void this.load();
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    const filters = this.filters.getRawValue();
    try {
      const query: NonNullable<ListScanCampaignsData['query']> = {
        offset: this.offset(),
        limit: this.limit,
        sort_by: 'updated_at',
        sort_order: 'desc',
      };
      if (filters.search.trim()) query.search = filters.search.trim();
      if (filters.status) query.status = filters.status as ScanCampaignResponse['status'];
      const page = await this.api.campaigns(this.projectId, query);
      this.campaigns.set(page.items);
      this.total.set(page.pagination.total);
      const summaries = await Promise.all(
        page.items.map(async (campaign) => {
          try {
            const summary = await this.api.summary(this.projectId, campaign.id);
            const total = Object.values(summary.page_scan_counts).reduce(
              (sum, count) => sum + count,
              0,
            );
            const complete =
              (summary.page_scan_counts['succeeded'] ?? 0) +
              (summary.page_scan_counts['failed'] ?? 0) +
              (summary.page_scan_counts['cancelled'] ?? 0);
            return [
              campaign.id,
              {
                percent: total === 0 ? 0 : Math.round((complete / total) * 100),
                label: `${String(complete)} of ${String(total)} visual scans complete`,
              },
            ] as const;
          } catch {
            return [campaign.id, { percent: 0, label: 'Progress unavailable' }] as const;
          }
        }),
      );
      const progress: Record<string, { readonly percent: number; readonly label: string }> = {};
      for (const [campaignId, value] of summaries) progress[campaignId] = value;
      this.progressByCampaign.set(progress);
    } catch (error: unknown) {
      this.error.set(error instanceof Error ? error.message : 'Campaigns could not be loaded.');
    } finally {
      this.loading.set(false);
    }
  }
}
