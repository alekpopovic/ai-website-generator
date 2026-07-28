import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import type { CrawlPageWithScansResponse, ListScanCampaignPagesData } from '@platform/api-client';

import { ScanReviewApiService } from '../../core/scans/scan-review-api.service';
import { EmptyStateComponent } from '../../shared/states/empty-state.component';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

@Component({
  imports: [ReactiveFormsModule, RouterLink, EmptyStateComponent, LoadingStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="scan-pages-heading">
      <h2 id="scan-pages-heading">Discovered pages</h2>
      <form class="filter-bar four-filters" [formGroup]="filters" (ngSubmit)="apply()">
        <label
          ><span>Status</span
          ><select class="text-input" formControlName="status">
            <option value="">All</option>
            <option value="fetched">Fetched</option>
            <option value="failed">Failed</option>
            <option value="blocked">Blocked</option>
            <option value="discovered">Discovered</option>
          </select></label
        >
        <label
          ><span>Page type</span
          ><select class="text-input" formControlName="pageType">
            <option value="">All</option>
            @for (type of pageTypes; track type) {
              <option [value]="type">{{ type }}</option>
            }
          </select></label
        >
        <label><span>Domain</span><input class="text-input" formControlName="domain" /></label>
        <button class="secondary-button" type="submit">Apply filters</button>
      </form>
      @if (loading()) {
        <app-loading-state label="Loading discovered pages…" />
      } @else if (error()) {
        <div class="state-card" role="alert">{{ error() }}</div>
      } @else if (pages().length === 0) {
        <app-empty-state
          heading="No pages found"
          message="No persisted pages match these filters."
        />
      } @else {
        <div class="table-scroll">
          <table class="data-table">
            <caption class="visually-hidden">
              Discovered scan pages
            </caption>
            <thead>
              <tr>
                <th scope="col">Page</th>
                <th scope="col">Domain</th>
                <th scope="col">Type</th>
                <th scope="col">Status</th>
                <th scope="col">Representative</th>
              </tr>
            </thead>
            <tbody>
              @for (page of pages(); track page.id) {
                <tr>
                  <th scope="row">
                    <a [routerLink]="[page.id]">{{ page.title || page.normalized_url }}</a
                    ><small>{{ page.normalized_url }}</small>
                  </th>
                  <td>{{ page.source_domain }}</td>
                  <td>{{ page.page_type || 'unclassified' }}</td>
                  <td>
                    <span class="status-pill" [attr.data-state]="page.status">{{
                      page.status
                    }}</span>
                  </td>
                  <td>{{ page.representative_selected ? 'Selected' : 'Not selected' }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
        <nav class="pagination-controls" aria-label="Discovered page pages">
          <button
            class="secondary-button"
            type="button"
            [disabled]="offset() === 0"
            (click)="previous()"
          >
            Previous</button
          ><span>{{ offset() + 1 }}–{{ Math.min(offset() + limit, total()) }} of {{ total() }}</span
          ><button
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
export class ScanPageListComponent {
  private readonly api = inject(ScanReviewApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly formBuilder = inject(FormBuilder);
  readonly Math = Math;
  readonly limit = 20;
  readonly offset = signal(0);
  readonly total = signal(0);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly pages = signal<readonly CrawlPageWithScansResponse[]>([]);
  readonly pageTypes = [
    'homepage',
    'about',
    'services',
    'product',
    'features',
    'pricing',
    'contact',
    'documentation',
    'blog-index',
    'article',
    'case-study',
    'careers',
    'legal',
    'authentication',
    'unknown',
  ] as const;
  readonly filters = this.formBuilder.nonNullable.group({ status: '', pageType: '', domain: '' });
  private readonly projectId = this.param('projectId');
  private readonly campaignId = this.param('campaignId');
  constructor() {
    void this.load();
  }
  apply(): void {
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
    const value = this.filters.getRawValue();
    const query: NonNullable<ListScanCampaignPagesData['query']> = {
      offset: this.offset(),
      limit: this.limit,
    };
    if (value.status) query.status = value.status as NonNullable<typeof query.status>;
    if (value.pageType) query.page_type = value.pageType as NonNullable<typeof query.page_type>;
    if (value.domain.trim()) query.domain = value.domain.trim().toLowerCase();
    try {
      const page = await this.api.pages(this.projectId, this.campaignId, query);
      this.pages.set(page.items);
      this.total.set(page.pagination.total);
    } catch (error: unknown) {
      this.error.set(error instanceof Error ? error.message : 'Pages could not be loaded.');
    } finally {
      this.loading.set(false);
    }
  }
  private param(name: string): string {
    for (const route of [...this.route.pathFromRoot].reverse()) {
      const value = route.snapshot.paramMap.get(name);
      if (value) return value;
    }
    return '';
  }
}
